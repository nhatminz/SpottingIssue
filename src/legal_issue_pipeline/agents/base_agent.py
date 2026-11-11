from __future__ import annotations
import json
import logging
from typing import Callable, TypeVar
from pydantic import BaseModel, ValidationError
from ..config import PipelineConfig
from ..llm.base_client import LLMClient, LLMError

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)


def reject_duplicate_keys(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse_structured(content: str, schema: type[T]) -> T:
    content = content.strip()
    if content.startswith("```json") and content.endswith("```"):
        content = content[7:-3].strip()
    elif content.startswith("```") and content.endswith("```"):
        content = content[3:-3].strip()
    json.loads(content, object_pairs_hook=reject_duplicate_keys,
               parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")))
    return schema.model_validate_json(content)


class BaseAgent:
    def __init__(self, client: LLMClient, config: PipelineConfig, prompt_name: str):
        self.client, self.config = client, config
        self.scope_prompt = (config.prompt_dir/"benchmark_scope.md").read_text(encoding="utf-8")
        self.system_prompt = (config.prompt_dir/prompt_name).read_text(encoding="utf-8")+"\n"+self.scope_prompt
        # Agent instances belong to one case, never shared between workers/cases.
        self.message_history: list[list[dict]] = []
        self.request_metrics: list[dict] = []

    async def infer(self, payload: dict, schema: type[T], instruction: str = "", validate: Callable[[T], None] | None = None,
                    system_prompt_override: str | None = None) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system = self.system_prompt if system_prompt_override is None else system_prompt_override+"\n"+self.scope_prompt
        messages = [{"role": "system", "content": system+"\n"+instruction+"\nReturn ONLY a JSON object conforming to this JSON Schema:\n"+schema_json},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        for attempt in range(self.config.max_json_repair_retries+1):
            self.message_history.append(json.loads(json.dumps(messages)))
            completion = await self.client.complete(messages, schema.model_json_schema())
            self.request_metrics.append({"request_id": completion.request_id, "latency_seconds": completion.latency_seconds,
                                         "usage": completion.usage if self.config.save_token_usage else {}})
            try:
                parsed = parse_structured(completion.content, schema)
                if validate:
                    validate(parsed)
                return parsed
            except (ValueError, ValidationError) as exc:
                # Only error type/field locations, never reflect Judge's private text
                # into another role's prompts. Retry remains within the same agent.
                if isinstance(exc, ValidationError):
                    detail = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
                else:
                    detail = str(exc)[:300]
                log.warning("%s structured validation failed attempt=%d details=%s", type(self).__name__, attempt+1, detail)
                if attempt == self.config.max_json_repair_retries:
                    raise LLMError(f"{type(self).__name__}: structured validation exhausted: {detail}") from None
                messages.extend([{"role": "assistant", "content": completion.content},
                                 {"role": "user", "content": "Repair your JSON; preserve supported facts only. Errors: "+json.dumps(detail,ensure_ascii=False)}])
        raise AssertionError("unreachable")
