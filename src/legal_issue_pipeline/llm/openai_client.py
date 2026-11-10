from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from copy import deepcopy
from uuid import uuid4

import httpx

from ..config import AgentConfig, PipelineConfig
from .adapters import DeepSeekAdapter, GenericAdapter
from .base_client import Completion, ContextLimitError, LLMError

log = logging.getLogger(__name__)


class OpenAICompatibleClient:
    def __init__(self, agent: AgentConfig, config: PipelineConfig, semaphore: asyncio.Semaphore,
                 role: str, transport: httpx.AsyncBaseTransport | None = None, tokenizer=None):
        self.agent, self.config, self.role = agent, config, role
        self.semaphore = semaphore
        self.http = httpx.AsyncClient(timeout=agent.timeout or config.api_request_timeout, transport=transport, trust_env=False)
        self.parameters, self.effective_thinking = (DeepSeekAdapter() if agent.backend == "deepseek" else GenericAdapter()).parameters(agent, config)
        self.tokenizer = tokenizer
        self.rng = random.Random(config.random_seed)
        self.calls: list[dict] = []

    def build_body(self, messages: list[dict], schema: dict) -> dict:
        body = {"model": self.agent.model, "messages": deepcopy(messages), "max_tokens": self.agent.max_output_tokens, "stream": False, **deepcopy(self.parameters)}
        if self.config.require_structured_output:
            body["response_format"] = ({"type": "json_schema", "json_schema": {"name": "agent_output", "strict": True, "schema": schema}} if self.agent.structured_output_mode == "json_schema" else {"type": "json_object"})
        for extra in [self.config.api_extra_body, self.agent.extra_body]:
            forbidden = {"messages", "model", "stream", "max_tokens", "response_format"} & extra.keys()
            if forbidden:
                raise ValueError(f"Extra body cannot override isolation/validation fields: {sorted(forbidden)}")
            collisions = body.keys() & extra.keys()
            if collisions:
                log.warning("Explicit extra-body overrides adapter keys: %s", sorted(collisions))
            body.update(deepcopy(extra))
        if self.agent.stop:
            body["stop"] = self.agent.stop
        return body

    def _check_context(self, body: dict) -> None:
        messages = body["messages"]
        if self.tokenizer is not None:
            # Schema is already embedded in the system message.
            length = len(self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True))
            method = "tokenizer"
        else:
            # Conservative bound: byte-fallback tokenizers cannot exceed one token/byte.
            length = sum(len(m["content"].encode("utf-8")) + 32 for m in messages)
            method = "utf8_byte_upper_bound"
        if length > self.config.max_input_tokens or length + body["max_tokens"] > self.config.max_context_tokens:
            raise ContextLimitError(f"Context too large ({length}, method={method}); no text was truncated")

    async def complete(self, messages: list[dict], schema: dict) -> Completion:
        body = self.build_body(messages, schema)
        self._check_context(body)
        headers = {"Authorization": "Bearer " + self.agent.api_key.get_secret_value()}
        request_id = uuid4().hex
        start = time.monotonic()
        for attempt in range(self.agent.max_retries + 1):
            try:
                async with self.semaphore:
                    response = await self.http.post(self.agent.api_base.rstrip("/")+"/chat/completions", json=body, headers=headers)
                if response.status_code in [408, 409, 429] or response.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable endpoint status", request=response.request, response=response)
                if response.is_error:
                    # No full response body or credentials in exceptions/logs.
                    raise LLMError(f"{self.role} API HTTP {response.status_code}; check backend parameters (no automatic fallback)")
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise LLMError(f"{self.role} returned no final content")
                # reasoning_content is never read, stored, or forwarded.
                elapsed = time.monotonic() - start
                usage = data.get("usage") or {}
                call = {"role": self.role, "request_id": request_id, "attempts": attempt+1, "latency_seconds": elapsed, "effective_thinking": self.effective_thinking,"finish_reason":choice.get("finish_reason"),
                        "actual_thinking_parameters": {k: body[k] for k in ["thinking", "reasoning_effort", "chat_template_kwargs"] if k in body}, "usage": usage if self.config.save_token_usage else {}}
                if isinstance(call["actual_thinking_parameters"].get("chat_template_kwargs"),dict):
                    call["actual_thinking_parameters"]["chat_template_kwargs"] = {
                        k:v for k,v in body["chat_template_kwargs"].items()
                        if k in ["enable_thinking", "thinking"] and type(v) is bool}
                if self.config.save_raw_responses:
                    # Save answer text only; even raw mode excludes model reasoning.
                    call["raw_final_content"] = discard_reasoning_tags(content)
                self.calls.append(call)
                if choice.get("finish_reason") not in [None, "stop"]:
                    raise LLMError(f"{self.role} incomplete completion: finish_reason={choice.get('finish_reason')}")
                return Completion(discard_reasoning_tags(content), usage, elapsed, request_id)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                self.calls.append({"role": self.role, "request_id": request_id, "attempt": attempt+1, "api_error": str(status)})
                log.warning("%s API request %s failed: %s, attempt %d", self.role, request_id, status, attempt+1)
                if attempt == self.agent.max_retries:
                    raise LLMError(f"{self.role} request exhausted retries: {status}") from None
                delay = self.config.retry_backoff * 2**attempt + self.rng.uniform(0, self.config.retry_jitter)
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        delay = max(delay, min(float(exc.response.headers.get("retry-after", 0)), 60))
                    except ValueError:
                        pass
                await asyncio.sleep(delay)
            except (ValueError, KeyError, IndexError, TypeError):
                raise LLMError(f"{self.role} malformed API envelope") from None
        raise AssertionError("unreachable")

    async def close(self) -> None:
        await self.http.aclose()


def discard_reasoning_tags(content: str) -> str:
    if "</think>" in content:
        return content.rsplit("</think>", 1)[1].strip()
    if "<think>" in content:
        raise LLMError("Unclosed reasoning tag without final answer")
    return content
