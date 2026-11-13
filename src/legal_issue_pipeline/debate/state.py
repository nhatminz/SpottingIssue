from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from ..schemas import GeneratorOutput, JudgeOutput


class CaseStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass
class EvaluatedCandidate:
    output: GeneratorOutput
    judgment: JudgeOutput
    errors: list[str]
    round_index: int


@dataclass
class DebateResult:
    issues: list[str]
    explain: list[str]
    status: CaseStatus
    audit: dict = field(default_factory=dict)
