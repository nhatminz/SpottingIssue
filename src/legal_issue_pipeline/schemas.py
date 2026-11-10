"""Only explicit, inspectable structured exchanges cross the agent boundary."""
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Structured(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ErrorCode(str, Enum):
    INVALID_FORMAT = "INVALID_FORMAT"
    UNSUPPORTED_FACT = "UNSUPPORTED_FACT"
    WRONG_LIABILITY = "WRONG_LIABILITY"
    MISSING_CORE_ISSUE = "MISSING_CORE_ISSUE"
    DUPLICATE = "DUPLICATE"
    NON_ATOMIC = "NON_ATOMIC"
    LOW_RELEVANCE = "LOW_RELEVANCE"
    PREMATURE_CONCLUSION = "PREMATURE_CONCLUSION"


class Issue(Structured):
    issue_id: str = Field(min_length=1)
    issue_text: str = Field(min_length=10)
    focus_group: Literal["LIABILITY", "VALIDITY", "DETERMINATION", "PROCEDURE"]
    focus: str = Field(min_length=1)
    subject_action: str = Field(min_length=1)
    decisive_fact: str = Field(min_length=1)
    situation_evidence_quotes: list[str] = Field(min_length=1)
    importance: Literal["CORE", "RELATED"]


class FeedbackResponse(Structured):
    feedback_id: str
    decision: Literal["ACCEPT", "CONTEST", "PARTIALLY_ACCEPT"]
    explanation: str = Field(min_length=1,max_length=1500)
    situation_evidence_quotes: list[str]


class GeneratorOutput(Structured):
    issues: list[Issue]
    responses_to_feedback: list[FeedbackResponse]


class Feedback(Structured):
    feedback_id: str
    issue_ids: list[str]
    error_code: ErrorCode
    action: Literal["REVISE", "REMOVE", "ADD", "SPLIT", "RECONSIDER"]
    situation_evidence_quotes: list[str] = Field(min_length=1)
    # Narrative is PRIVATE. The firewall forwards only enum/id/verified quotes.
    explanation: str = Field(min_length=1,max_length=1500)


class IssueReview(Structured):
    issue_id: str
    verdict: Literal["PASS", "REVISE", "REMOVE", "NEEDS_REVIEW"]
    error_codes: list[ErrorCode]
    explanation: str = Field(min_length=1,max_length=1500)
    situation_evidence_quotes: list[str]


class RebuttalAssessment(Structured):
    feedback_id: str
    decision: Literal["WITHDRAW", "UPHOLD", "PARTIALLY_WITHDRAW"]
    explanation: str = Field(min_length=1,max_length=1500)
    situation_evidence_quotes: list[str] = Field(min_length=1)


class FactFinding(Structured):
    fact: str = Field(min_length=1)
    markdown_evidence_quotes: list[str] = Field(min_length=1)
    material: bool
    importance_reason: str = Field(min_length=1)
    affected_issue: str = Field(min_length=1)
    equivalent_in_situation: bool
    equivalence_assessment: str = Field(min_length=1)


class SituationAudit(Structured):
    missing_facts: list[FactFinding]
    contradictions: list[FactFinding]
    needs_review: bool
    explanation: str = Field(min_length=1,max_length=1500)


class JudgeOutput(Structured):
    per_issue_reviews: list[IssueReview]
    error_codes: list[ErrorCode]
    feedback: str = Field(max_length=1500)
    suggested_missing_issues: list[Issue]
    generator_visible_feedback: list[Feedback]
    rebuttal_assessments: list[RebuttalAssessment]
    situation_audit: SituationAudit
    overall_verdict: Literal["PASS", "REVISE", "NEEDS_REVIEW"]
    unresolved_disputes: list[str]


class DiscoveryOutput(Structured):
    issues: list[Issue]


class SafeFeedback(Structured):
    feedback_id: str
    issue_ids: list[str]
    error_code: ErrorCode
    action: Literal["REVISE", "REMOVE", "ADD", "SPLIT", "RECONSIDER"]
    situation_evidence_quotes: list[str]


class SafeAssessment(Structured):
    feedback_id: str
    decision: Literal["WITHDRAW", "UPHOLD", "PARTIALLY_WITHDRAW"]
    situation_evidence_quotes: list[str]
