import asyncio
import json
import httpx
import pytest
from legal_issue_pipeline.config import AgentConfig
from legal_issue_pipeline.llm.adapters import DeepSeekAdapter,GenericAdapter
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient,discard_reasoning_tags
from legal_issue_pipeline.llm.base_client import LLMError,ContextLimitError


@pytest.mark.parametrize("requested,expected",[("extra_high","max"),("medium","high"),("low","low"),("high","high"),("max","max")])
def test_deepseek_mapping(config,requested,expected):
    config.gen.thinking_effort=requested
    config.gen.temperature=0.7
    body,effective=DeepSeekAdapter().parameters(config.gen,config)
    assert body["reasoning_effort"]==expected
    assert "temperature" not in body and effective["effective_effort"]==expected


def test_unsupported_effort_fail_or_explicit_fallback(config):
    config.gen.supported_efforts=["high"]
    with pytest.raises(ValueError,match="Unsupported"):
        DeepSeekAdapter().parameters(config.gen,config)
    config.thinking_unsupported_policy="fallback"
    assert DeepSeekAdapter().parameters(config.gen,config)[0]["reasoning_effort"]=="high"


def test_qwen_uses_switch_not_deepseek_params(config):
    agent=AgentConfig(backend="generic",thinking_enabled=False,thinking_effort="none")
    body,_=GenericAdapter().parameters(agent,config)
    assert body["chat_template_kwargs"]=={"enable_thinking":False}
    assert "thinking" not in body and "reasoning_effort" not in body
    agent.thinking_enabled=True;agent.thinking_effort="extra_high"
    with pytest.raises(ValueError):
        GenericAdapter().parameters(agent,config)


async def test_retry_success_and_reasoning_not_saved(config):
    tries=0
    def handler(request):
        nonlocal tries
        tries+=1
        if tries==1:
            return httpx.Response(429)
        return httpx.Response(200,json={"choices":[{"message":{"content":"{}","reasoning_content":"PRIVATE_REASONING"},"finish_reason":"stop"}],"usage":{"total_tokens":7}})
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),"gen",httpx.MockTransport(handler))
    result=await client.complete([{"role":"user","content":"test"}],{})
    assert tries==2 and result.content=="{}"
    assert "PRIVATE_REASONING" not in json.dumps(client.calls)
    await client.close()


@pytest.mark.parametrize("kind",["timeout","unavailable","server_error"])
async def test_retry_exhausted(config,kind):
    config.gen.max_retries=1
    tries=0
    def handler(request):
        nonlocal tries
        tries+=1
        if kind=="timeout":raise httpx.ReadTimeout("secret error",request=request)
        if kind=="unavailable":raise httpx.ConnectError("secret error",request=request)
        return httpx.Response(503)
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),"gen",httpx.MockTransport(handler))
    with pytest.raises(LLMError,match="exhausted retries"):
        await client.complete([{"role":"user","content":"test"}],{})
    assert tries==2
    await client.close()


async def test_no_implicit_http400_fallback(config):
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),"gen",httpx.MockTransport(lambda r:httpx.Response(400,text="PRIVATE_SECRET")))
    with pytest.raises(LLMError,match="HTTP 400") as e:
        await client.complete([{"role":"user","content":"test"}],{})
    assert "PRIVATE_SECRET" not in str(e.value)
    await client.close()


async def test_context_never_silently_truncated(config):
    config.max_input_tokens=512
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),"gen")
    with pytest.raises(ContextLimitError):
        await client.complete([{"role":"user","content":"x"*513}],{})
    await client.close()


async def test_protected_extra_body(config):
    config.api_extra_body={"messages":[]}
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),"gen")
    with pytest.raises(ValueError,match="cannot override"):
        client.build_body([], {})
    await client.close()


def test_discard_reasoning():
    assert discard_reasoning_tags("<think>secret</think>{}")=="{}"
    with pytest.raises(LLMError):discard_reasoning_tags("<think>unfinished")


async def test_incomplete_completion_keeps_sanitized_diagnostics(config):
    config.save_raw_responses=True
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"choices":[{"message":{
        "content":'<think>PRIVATE_REASONING</think>{"issues":',"reasoning_content":"PRIVATE_REASONING"},"finish_reason":"length"}],
        "usage":{"total_tokens":100}}))
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),"gen",transport)
    with pytest.raises(LLMError,match="finish_reason=length"):
        await client.complete([{"role":"user","content":"test"}],{})
    assert client.calls[0]["usage"]["total_tokens"]==100
    assert client.calls[0]["finish_reason"]=="length"
    assert "PRIVATE_REASONING" not in json.dumps(client.calls)
    await client.close()
