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
