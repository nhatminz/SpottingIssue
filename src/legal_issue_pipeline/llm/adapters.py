"""Backend-specific request parameters. No implicit fallbacks after HTTP 400."""
from __future__ import annotations
import logging
from ..config import AgentConfig, PipelineConfig

log = logging.getLogger(__name__)


def _effort(agent: AgentConfig, config: PipelineConfig) -> str:
    requested = agent.thinking_effort
    mapped = {"extra_high": "max", "medium": "high"}.get(requested, requested)
    if mapped != requested:
        log.warning("thinking effort alias %s -> %s (%s)", requested, mapped, agent.backend)
    if mapped not in agent.supported_efforts:
        if config.thinking_unsupported_policy == "fail":
            raise ValueError(f"Unsupported thinking effort {mapped}; supported={agent.supported_efforts}")
        if agent.fallback_effort not in agent.supported_efforts:
            raise ValueError("Fallback effort is also unsupported")
        log.warning("Unsupported effort %s -> configured fallback %s", mapped, agent.fallback_effort)
        mapped = agent.fallback_effort
    return mapped


class GenericAdapter:
    def parameters(self, agent: AgentConfig, config: PipelineConfig) -> tuple[dict, dict]:
        body: dict = {}
        effective: dict = {"thinking_enabled": agent.thinking_enabled, "requested_effort": agent.thinking_effort, "effective_effort": None}
        if agent.generic_thinking_style == "qwen":
            body["chat_template_kwargs"] = {"enable_thinking": agent.thinking_enabled}
            if agent.thinking_enabled and agent.thinking_effort not in ["none", ""]:
                if config.thinking_unsupported_policy == "fail":
                    raise ValueError("Qwen switch has no compute-effort levels; use effort=none or fallback policy")
                log.warning("Qwen effort=%s unsupported; explicit fallback to thinking switch only", agent.thinking_effort)
        elif agent.generic_thinking_style == "reasoning_effort":
            level = _effort(agent, config) if agent.thinking_enabled else "none"
            body["reasoning_effort"] = level
            effective["effective_effort"] = level
        elif agent.thinking_enabled:
            raise ValueError("generic_thinking_style=none cannot enable thinking")
        for name in ["temperature", "top_p", "seed"]:
            if getattr(agent, name) is not None:
                body[name] = getattr(agent, name)
        return body, effective


class DeepSeekAdapter:
    def parameters(self, agent: AgentConfig, config: PipelineConfig) -> tuple[dict, dict]:
        body: dict = {"thinking": {"type": "enabled" if agent.thinking_enabled else "disabled"}}
        level = _effort(agent, config) if agent.thinking_enabled else None
        effective = {"thinking_enabled": agent.thinking_enabled, "requested_effort": agent.thinking_effort, "effective_effort": level}
        if level:
            body["reasoning_effort"] = level
        for name in ["temperature", "top_p", "seed"]:
            value = getattr(agent, name)
            if value is None:
                continue
            if agent.thinking_enabled or name == "seed":
                # Deliberately conservative across DeepSeek and self-hosted variants.
                # Flash top_p can work on some versions; extra_body explicitly opts in.
                log.warning("DeepSeek adapter omits configured %s=%s; backend/mode support not guaranteed. Use explicit extra body to opt in.", name, value)
            else:
                body[name] = value
        return body, effective


class DeepSeekVLLMAdapter:
    """DeepSeek V4.1's open-source encoder: four aliases or a 1..100 budget.

    This is deliberately separate from the hosted DeepSeek API's tier mapping.
    https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4.1-Flash
    """
    tiers = {"low": 25, "high": 50, "xhigh": 75, "max": 100}

    @classmethod
    def validate_body(cls, body: dict) -> None:
        """Check the final merged template options, including explicit extra-body overrides."""
        kwargs = body.get("chat_template_kwargs", {})
        if not isinstance(kwargs, dict):
            raise ValueError("chat_template_kwargs must be an object")
        switches = [kwargs[key] for key in ["thinking", "enable_thinking"] if key in kwargs]
        if any(type(value) is not bool for value in switches) or len(set(switches)) > 1:
            raise ValueError("vLLM thinking/enable_thinking must be booleans and must agree")
        if "reasoning_effort" in kwargs:
            value = kwargs["reasoning_effort"]
            if not ((type(value) is int and 1 <= value <= 100) or
                    (isinstance(value, str) and value in cls.tiers)):
                raise ValueError("vLLM chat_template_kwargs.reasoning_effort must be a native tier or integer 1-100")
        top_level = body.get("reasoning_effort")
        if top_level is not None:
            if not isinstance(top_level, str) or top_level not in {*cls.tiers, "none"}:
                raise ValueError("vLLM top-level reasoning_effort must be none, low, high, xhigh, or max")
            if switches and any(switches) != (top_level != "none"):
                raise ValueError("vLLM top-level reasoning_effort conflicts with the thinking switch")
            nested = kwargs.get("reasoning_effort")
            if top_level != "none" and nested is not None and cls.tiers[top_level] != cls.tiers.get(nested, nested):
                raise ValueError("vLLM top-level and template reasoning_effort must agree")

    def _budget(self, value: str | int, agent: AgentConfig) -> int:
        if value == "extra_high":
            log.warning("thinking effort alias extra_high -> max (deepseek_vllm; legacy pipeline alias)")
            value = "max"
        if type(value) is int and 1 <= value <= 100:
            return value
        if isinstance(value, str) and value in self.tiers and value in agent.supported_efforts:
            return self.tiers[value]
        raise ValueError("DeepSeek vLLM effort must be low, high, xhigh, max, or an integer 1-100; "
                         f"got {value!r} (supported aliases={agent.supported_efforts})")

    def parameters(self, agent: AgentConfig, config: PipelineConfig) -> tuple[dict, dict]:
        enabled = agent.thinking_enabled and agent.thinking_effort != "none"
        if agent.thinking_enabled and not enabled:
            log.warning("deepseek_vllm effort=none disables thinking")
        budget = None
        if enabled:
            try:
                budget = self._budget(agent.thinking_effort, agent)
            except ValueError:
                if config.thinking_unsupported_policy == "fail":
                    raise
                budget = self._budget(agent.fallback_effort, agent)
                log.warning("Unsupported vLLM effort %s -> configured fallback %s (budget=%d)",
                            agent.thinking_effort, agent.fallback_effort, budget)
        kwargs = {"thinking": enabled}
        if budget is not None:
            kwargs["reasoning_effort"] = budget
        body = {"chat_template_kwargs": kwargs}
        # vLLM sampling parameters are independent of the numeric reasoning budget.
        for name in ["temperature", "top_p", "seed"]:
            if getattr(agent, name) is not None:
                body[name] = getattr(agent, name)
        return body, {"thinking_enabled": enabled, "requested_effort": agent.thinking_effort,
                      "effective_effort": budget, "backend": "deepseek_vllm"}


def adapter_for(agent: AgentConfig):
    return {"deepseek": DeepSeekAdapter, "deepseek_vllm": DeepSeekVLLMAdapter,
            "generic": GenericAdapter}[agent.backend]()
