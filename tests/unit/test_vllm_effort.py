import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from legal_issue_pipeline.config import AgentConfig, load_config
from legal_issue_pipeline.llm.adapters import DeepSeekAdapter, DeepSeekVLLMAdapter
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient
from legal_issue_pipeline.pipeline.runner import PipelineRunner


@pytest.mark.parametrize("effort,budget", [
    ("low", 25), ("high", 50), ("xhigh", 75), ("max", 100),
    (1, 1), (42, 42), (75, 75), (100, 100), ("73", 73), ("extra_high", 100),
])
def test_vllm_native_tiers_and_numeric_budget(config, effort, budget):
    agent = AgentConfig(backend="deepseek_vllm", thinking_effort=effort)
    body, effective = DeepSeekVLLMAdapter().parameters(agent, config)
    assert body == {"chat_template_kwargs": {"thinking": True, "reasoning_effort": budget}}
    assert type(body["chat_template_kwargs"]["reasoning_effort"]) is int
    assert effective["effective_effort"] == budget


@pytest.mark.parametrize("effort", ["medium", "minimal", "ultra", "bad", 0, 101, -1, "75.5"])
def test_vllm_rejects_invalid_effort_without_implicit_mapping(config, effort):
    agent = AgentConfig(backend="deepseek_vllm", thinking_effort=effort)
    with pytest.raises(ValueError, match="integer 1-100"):
        DeepSeekVLLMAdapter().parameters(agent, config)


@pytest.mark.parametrize("effort", [True, False, 25.5])
def test_budget_does_not_coerce_booleans_or_floats(effort):
    with pytest.raises(ValidationError):
        AgentConfig(thinking_effort=effort)


@pytest.mark.parametrize("enabled,effort", [(False, "max"), (True, "none"), (False, "none")])
def test_vllm_explicitly_disables_thinking(config, enabled, effort):
    body, effective = DeepSeekVLLMAdapter().parameters(
        AgentConfig(thinking_enabled=enabled, thinking_effort=effort), config)
    assert body == {"chat_template_kwargs": {"thinking": False}}
    assert effective["thinking_enabled"] is False and effective["effective_effort"] is None


def test_vllm_fallback_is_explicit_and_logged(config, caplog):
    config.thinking_unsupported_policy = "fallback"
    agent = AgentConfig(thinking_effort="medium", fallback_effort=63)
    body, _ = DeepSeekVLLMAdapter().parameters(agent, config)
    assert body["chat_template_kwargs"]["reasoning_effort"] == 63
    assert "configured fallback 63" in caplog.text
    agent.fallback_effort = "minimal"
    with pytest.raises(ValueError):
        DeepSeekVLLMAdapter().parameters(agent, config)


def test_hosted_api_retains_separate_tier_semantics(config):
    api = AgentConfig(backend="deepseek", thinking_effort="high")
    vllm = AgentConfig(backend="deepseek_vllm", thinking_effort="high")
    assert DeepSeekAdapter().parameters(api, config)[0]["reasoning_effort"] == "high"
    assert DeepSeekVLLMAdapter().parameters(vllm, config)[0]["chat_template_kwargs"]["reasoning_effort"] == 50
    api.thinking_effort = "extra_high"
    assert DeepSeekAdapter().parameters(api, config)[0]["reasoning_effort"] == "max"


def test_numeric_budget_from_environment(monkeypatch):
    monkeypatch.setenv("GEN_BACKEND", "deepseek_vllm")
    monkeypatch.setenv("GEN_THINKING_EFFORT", "61")
    monkeypatch.setenv("JUDGE_THINKING_EFFORT", "xhigh")
    config = load_config()
    assert config.gen.thinking_effort == 61
    body, _ = DeepSeekVLLMAdapter().parameters(config.gen, config)
    assert body["chat_template_kwargs"]["reasoning_effort"] == 61


@pytest.mark.parametrize("role", ["gen", "judge"])
def test_preflight_catches_effort_error_before_any_record_or_checkpoint(config, record, role):
    config.input_path.write_text(json.dumps(record) + "\n")
    getattr(config, role).thinking_effort = "medium"
    with pytest.raises(ValueError, match=f"{role} configuration"):
        PipelineRunner(config).preflight()
    assert not config.checkpoint_dir.exists() and not config.output_path.exists()


@pytest.mark.parametrize("body", [
    {"chat_template_kwargs": {"thinking": True, "enable_thinking": False}},
    {"chat_template_kwargs": {"thinking": "true"}},
    {"chat_template_kwargs": {"thinking": True, "reasoning_effort": "medium"}},
    {"chat_template_kwargs": {"thinking": True, "reasoning_effort": True}},
    {"chat_template_kwargs": {"thinking": True, "reasoning_effort": 101}},
    {"chat_template_kwargs": {"thinking": True}, "reasoning_effort": "none"},
    {"chat_template_kwargs": {"thinking": True, "reasoning_effort": 75}, "reasoning_effort": "high"},
])
def test_conflicting_or_invalid_template_options_cannot_reach_server(body):
    with pytest.raises(ValueError):
        DeepSeekVLLMAdapter.validate_body(body)


async def test_real_http_body_and_sanitized_audit_preserve_numeric_effort(config):
    config.gen = AgentConfig(thinking_effort=67, temperature=0.8, top_p=0.95, seed=42)
    config.gen.extra_body = {"chat_template_kwargs": {
        "thinking": True, "enable_thinking": True, "reasoning_effort": 67, "private_option": "DO_NOT_LOG"}}
    def handler(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 131073
        assert "reasoning_effort" not in body and "thinking" not in body
        assert body["chat_template_kwargs"]["reasoning_effort"] == 67
        assert body["temperature"] == 0.8 and body["top_p"] == 0.95 and body["seed"] == 42
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "{}", "reasoning_content": "PRIVATE_REASONING"}, "finish_reason": "stop"}]})
    client = OpenAICompatibleClient(config.gen, config, asyncio.Semaphore(1), "gen", httpx.MockTransport(handler))
    try:
        await client.complete([{"role": "user", "content": "test"}], {})
        actual = client.calls[0]["actual_thinking_parameters"]
        assert actual == {"chat_template_kwargs": {"thinking": True, "enable_thinking": True, "reasoning_effort": 67}}
        assert "DO_NOT_LOG" not in json.dumps(client.calls) and "PRIVATE_REASONING" not in json.dumps(client.calls)
    finally:
        await client.close()


async def test_40_request_limit_is_shared_across_both_roles(config):
    active = peak = requests = 0
    full_wave = asyncio.Event()
    async def handler(request):
        nonlocal active, peak, requests
        active += 1
        requests += 1
        peak = max(peak, active)
        if active == 40:
            full_wave.set()
        try:
            await asyncio.wait_for(full_wave.wait(), timeout=5)
            await asyncio.sleep(0)
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
        finally:
            active -= 1
    semaphore = asyncio.Semaphore(40)
    clients = [OpenAICompatibleClient(getattr(config, role), config, semaphore, role, httpx.MockTransport(handler))
               for role in ["gen", "judge"]]
    try:
        await asyncio.gather(*(clients[index % 2].complete([{"role": "user", "content": "test"}], {}) for index in range(100)))
        assert peak == 40 and requests == 100
    finally:
        await asyncio.gather(*(client.close() for client in clients))
