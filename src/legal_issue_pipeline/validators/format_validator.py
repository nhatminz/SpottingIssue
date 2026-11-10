"""Mechanical checks only. Atomicity, liability basis and relevance remain semantic."""
from __future__ import annotations
import re
from ..config import PipelineConfig
from ..schemas import GeneratorOutput, Issue
from .evidence_validator import validate_quotes

PREFIXES = {
    "LIABILITY": ("Trách nhiệm pháp lý", "Trách nhiệm hình sự", "Trách nhiệm hành chính", "Trách nhiệm dân sự", "Trách nhiệm bồi thường thiệt hại"),
    "VALIDITY": ("Tính hợp pháp của", "Hiệu lực pháp lý của"),
    "DETERMINATION": ("Việc xác định tư cách", "Việc xác định đối tượng", "Việc xác định giá trị", "Việc xác định quyền và nghĩa vụ", "Việc xác định quyền", "Việc xác định nghĩa vụ"),
    "PROCEDURE": ("Thẩm quyền", "Thời hiệu", "Thủ tục giải quyết"),
}


def issue_errors(issue: Issue, situation: str, config: PipelineConfig) -> list[str]:
    errors = []
    if config.strict_format:
        text = issue.issue_text
        if not any(text.startswith(p+" ") for p in PREFIXES[issue.focus_group]):
            errors.append(f"INVALID_FORMAT:{issue.issue_id}:prefix/group")
        parts = re.split(r"\s+(?:khi|trong trường hợp)\s+", text, maxsplit=1)
        if len(parts) != 2 or not all(p.strip() for p in parts) or "\n" in text or "?" in text:
            errors.append(f"INVALID_FORMAT:{issue.issue_id}:three ordered components")
        if not text.startswith(issue.focus) or issue.subject_action not in text or issue.decisive_fact not in text:
            errors.append(f"INVALID_FORMAT:{issue.issue_id}:metadata not present in issue_text")
        elif len(parts) == 2 and (issue.subject_action not in parts[0] or issue.decisive_fact not in parts[1]):
            errors.append(f"INVALID_FORMAT:{issue.issue_id}:component order")
    if config.enable_evidence_validation:
        try:
            validate_quotes(issue.situation_evidence_quotes, situation, issue.issue_id)
        except ValueError:
            errors.append(f"UNSUPPORTED_FACT:{issue.issue_id}:non-verbatim evidence")
    return errors


def candidate_errors(output: GeneratorOutput, situation: str, config: PipelineConfig) -> list[str]:
    errors = [e for issue in output.issues for e in issue_errors(issue, situation, config)]
    ids = [i.issue_id for i in output.issues]
    if len(set(ids)) != len(ids):
        errors.append("INVALID_FORMAT:duplicate issue_id")
    if config.enable_deduplication:
        texts = [" ".join(i.issue_text.casefold().split()) for i in output.issues]
        if len(set(texts)) != len(texts):
            errors.append("DUPLICATE:identical issues (semantic duplicates also require Judge review)")
    return errors
