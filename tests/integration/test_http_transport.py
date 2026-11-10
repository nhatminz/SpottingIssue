"""Exercise real adapters/HTTP serialization plus the full runner without a GPU."""
import asyncio
import json
import httpx
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.config import AgentConfig
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from conftest import gen_data,judge_data


async def test_http_pipeline_two_distinct_requests(config,record):
    config.gen=AgentConfig(backend="generic",thinking_enabled=False,thinking_effort="none",api_key="test-secret")
    config.judge=config.gen.model_copy(deep=True)
    JSONLWriter(config.input_path).write([record])
    requests=[]
    def handler(request):
        body=json.loads(request.content)
        requests.append(body)
        assert request.headers["authorization"]=="Bearer test-secret"
        assert body["chat_template_kwargs"]=={"enable_thinking":False}
        payload=json.loads(body["messages"][1]["content"])
        if "current_candidate" in payload:
            assert payload["markdown"]==record["markdown"]
            answer=judge_data()
        else:
            assert payload=={"situation":record["situation"]}
            answer=gen_data()
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(answer),"reasoning_content":"DO_NOT_SAVE"},"finish_reason":"stop"}],
                                       "usage":{"prompt_tokens":100,"completion_tokens":40,"total_tokens":140}})
    def factory():
        sem=asyncio.Semaphore(1)
        gen=OpenAICompatibleClient(config.gen,config,sem,"gen",httpx.MockTransport(handler))
        judge=OpenAICompatibleClient(config.judge,config,sem,"judge",httpx.MockTransport(handler))
        assert gen.http is not judge.http
        return DebateController(GeneratorAgent(gen,config),JudgeAgent(judge,config),config)
    summary=await PipelineRunner(config,factory).run()
    assert len(requests)==2 and summary["completed"]==1
    assert summary["token_usage"]["total_tokens"]==280
    assert summary["effective_thinking"]["generator"]["thinking_enabled"] is False
    for p in config.audit_dir.iterdir():
        content=p.read_text()
        assert "test-secret" not in content and "DO_NOT_SAVE" not in content
