"""Typed, environment-driven configuration; shell is the user-facing control panel."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_base: str = "http://172.29.62.173:8000/v1"
    api_key: SecretStr = SecretStr("EMPTY")
    model: str = "DeepSeek-V4.1-Flash-1017"
    backend: Literal["deepseek", "generic"] = "deepseek"
    thinking_enabled: bool = True
    thinking_effort: str = "extra_high"
    # Generic Qwen supports a switch, not a guaranteed compute-effort dial.
    generic_thinking_style: Literal["qwen", "reasoning_effort", "none"] = "qwen"
    supported_efforts: list[str] = Field(default_factory=lambda: ["low", "high", "max"])
    fallback_effort: str = "high"
    structured_output_mode: Literal["json_object", "json_schema"] = "json_object"
    max_output_tokens: int = Field(131073, ge=64)
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    timeout: float | None = None
    max_retries: int = Field(3, ge=0, le=20)
    extra_body: dict = Field(default_factory=dict)
    stop: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_endpoint(self):
        parsed = urlsplit(self.api_base)
        if parsed.scheme not in ["http", "https"] or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API base must be an http(s) URL without credentials/query/fragment; use API_KEY instead")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("Timeout must be positive")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("Temperature must lie in [0,2]")
        if self.top_p is not None and not 0 < self.top_p <= 1:
            raise ValueError("top_p must lie in (0,1]")
        return self


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_root: Path = Path(__file__).resolve().parents[2]
    input_path: Path
    output_path: Path
    rejected_path: Path | None = None
    audit_dir: Path
    log_dir: Path
    checkpoint_dir: Path
    prompt_dir: Path
    resume: bool = True
    overwrite_output: bool = False
    cuda_visible_devices: str = ""
    max_workers: int = Field(1, ge=1)
    max_concurrent_requests: int = Field(1, ge=1)
    batch_size: int = Field(8, ge=1)
    start_index: int = Field(0, ge=0)
    limit: int = Field(0, ge=0)
    random_seed: int = 42
    gen: AgentConfig = Field(default_factory=AgentConfig)
    judge: AgentConfig = Field(default_factory=AgentConfig)
    max_debate_rounds: int = Field(8, ge=1, le=100)
    enable_early_stop: bool = True
    enable_generator_rebuttal: bool = True
    enable_judge_reconsideration: bool = True
    enable_blind_judge_discovery: bool = True
    stop_on_stagnation: bool = True
    max_stagnant_rounds: int = Field(2, ge=1)
    finalize_policy: Literal["best_valid", "last_valid"] = "best_valid"
    # Legacy policies are normalized; neither can export unapproved candidates.
    unresolved_policy: Literal["reject", "stop", "continue"] = "reject"
    strict_format: bool = True
    enable_evidence_validation: bool = True
    enable_deduplication: bool = True
    enable_coverage_check: bool = True
    enable_situation_audit: bool = True
    situation_error_policy: Literal["material_missing", "material_missing_or_contradiction"] = "material_missing"
    max_json_repair_retries: int = Field(2, ge=0, le=10)
    require_structured_output: bool = True
    max_context_tokens: int = Field(262144, ge=1024)
    max_input_tokens: int = Field(100000, ge=512)
    # Never silently truncate the judgment and then declare a verified situation.
    truncation_policy: Literal["error"] = "error"
    tokenizer_path: str | None = None
    api_request_timeout: float = Field(300, gt=0)
    retry_backoff: float = Field(1, ge=0)
    retry_jitter: float = Field(0.25, ge=0)
    api_extra_body: dict = Field(default_factory=dict)
    thinking_unsupported_policy: Literal["fail", "fallback"] = "fail"
    log_level: str = "INFO"
    save_debate_history: bool = True
    save_raw_responses: bool = False
    save_token_usage: bool = True
    dry_run: bool = False
    fail_on_record_error: bool = True

    @model_validator(mode="after")
    def paths_and_context(self):
        for name in ["project_root", "input_path", "output_path", "audit_dir", "log_dir", "checkpoint_dir", "prompt_dir"]:
            setattr(self, name, getattr(self, name).expanduser().resolve())
        self.rejected_path = (self.rejected_path or self.output_path.parent/"rejected_cases.jsonl").expanduser().resolve()
        if len({self.input_path,self.output_path,self.rejected_path}) != 3:
            raise ValueError("Input, output and rejected paths must differ")
        for directory in [self.audit_dir, self.log_dir, self.checkpoint_dir]:
            if directory == self.input_path or directory in self.input_path.parents:
                raise ValueError("Artifacts directory must not contain the input file")
            if directory == self.output_path or directory in self.output_path.parents:
                raise ValueError("Artifacts directory must not contain the main output file")
            if directory == self.rejected_path or directory in self.rejected_path.parents:
                raise ValueError("Artifacts directory must not contain the rejected cases file")
        if len({self.audit_dir, self.log_dir, self.checkpoint_dir}) != 3:
            raise ValueError("Audit, log, and checkpoint directories must differ")
        for agent in [self.gen, self.judge]:
            if agent.max_output_tokens >= self.max_context_tokens:
                raise ValueError("max_output_tokens must be smaller than context length")
        if self.unresolved_policy != "reject":
            logging.getLogger(__name__).warning("UNRESOLVED_POLICY=%s is deprecated; using reject. Only PASS cases may be exported.",self.unresolved_policy)
            self.unresolved_policy = "reject"
        return self

    def public_dict(self) -> dict:
        value = self.model_dump(mode="json")
        for role in ["gen", "judge"]:
            value[role].pop("api_key", None)
            # Extra body may contain credentials; log keys only.
            value[role]["extra_body"] = {k: "<configured>" for k in value[role]["extra_body"]}
        value["api_extra_body"] = {k: "<configured>" for k in value["api_extra_body"]}
        return value

    def semantic_dict(self) -> dict:
        value = self.model_dump(mode="json")
        runtime = {"resume", "overwrite_output", "max_workers", "max_concurrent_requests", "batch_size", "cuda_visible_devices", "log_level", "dry_run", "fail_on_record_error", "save_raw_responses", "save_token_usage", "save_debate_history", "retry_backoff", "retry_jitter", "api_request_timeout"}
        runtime |= {"project_root", "input_path", "output_path", "rejected_path", "audit_dir", "log_dir", "checkpoint_dir", "prompt_dir"}
        for k in runtime:
            value.pop(k, None)
        for role in ["gen", "judge"]:
            for k in ["api_key", "timeout", "max_retries"]:
                value[role].pop(k, None)
        return value


def _read_env(name: str, annotation: object, default: object):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if annotation in [dict, list[str]]:
        return json.loads(raw)
    if raw.lower() in ["none", "null", ""] and default is None:
        return None
    return raw


def load_config() -> PipelineConfig:
    root = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
    paths = dict(project_root=root, input_path=root/"input/judgment_with_situation.jsonl", output_path=root/"output/judgment_with_issues.jsonl", audit_dir=root/"output/audit", log_dir=root/"output/logs", checkpoint_dir=root/"output/checkpoints", prompt_dir=root/"prompts")
    values = {}
    for name, field in PipelineConfig.model_fields.items():
        if name in ["gen", "judge"]:
            continue
        default = paths.get(name, field.get_default(call_default_factory=True))
        values[name] = _read_env(name.upper(), field.annotation, default)
    for name, prefix in [("gen", "GEN"), ("judge", "JUDGE")]:
        agent_values = {key: _read_env(f"{prefix}_{key.upper()}", field.annotation, field.get_default(call_default_factory=True)) for key,field in AgentConfig.model_fields.items()}
        secret_file = os.environ.get(f"{prefix}_API_KEY_FILE")
        if secret_file and not os.environ.get(f"{prefix}_API_KEY"):
            agent_values["api_key"] = Path(secret_file).expanduser().read_text().strip()
        # Blank key in the shell means local unauthenticated endpoint.
        agent_values["api_key"] = agent_values["api_key"] or "EMPTY"
        values[name] = AgentConfig(**agent_values)
    return PipelineConfig(**values)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
