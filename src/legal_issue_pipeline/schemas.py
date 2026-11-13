"""Separate full-judgment Generator output from the facts-only Judge contract."""
from __future__ import annotations
from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

IssueId = Annotated[str, Field(pattern=r"^I[1-9][0-9]{0,5}$")]


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
    UNSUPPORTED_ISSUE = "UNSUPPORTED_ISSUE"
    SUPPORTING_FACT = "SUPPORTING_FACT"
    ANCILLARY_ISSUE = "ANCILLARY_ISSUE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INVALID_EXPLANATION = "INVALID_EXPLANATION"
    INCONSISTENT_EXPLANATION = "INCONSISTENT_EXPLANATION"


class Issue(Structured):
    issue_id: IssueId
    issue_text: str = Field(min_length=10)
    explain: str = Field(min_length=20, max_length=2000)
    focus_group: Literal["LIABILITY", "VALIDITY", "DETERMINATION", "PROCEDURE"]
    focus: str = Field(min_length=1)
    subject_action: str = Field(min_length=1)
    decisive_fact: str = Field(min_length=1)
    facts_evidence_quotes: list[str] = Field(min_length=1)
    explanation_evidence_quotes: list[str] = Field(min_length=1)
    importance: Literal["CORE"]


class JudicialSupport(Structured):
    issue_id: str = Field(pattern=r"^I[1-9][0-9]{0,5}$")
    application_evidence_quotes: list[str] = Field(min_length=1)
    conclusion_evidence_quotes: list[str] = Field(min_length=1)
    judicial_relevance_confirmed: bool
    conclusion_consistent: bool
    explanation: str = Field(min_length=1, max_length=1500)


class FeedbackResponse(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["ACCEPT", "CONTEST", "PARTIALLY_ACCEPT"]
    explanation: str = Field(min_length=1, max_length=1500)
    facts_evidence_quotes: list[str]


class GeneratorOutput(Structured):
    issues: list[Issue]
    responses_to_feedback: list[FeedbackResponse]
    private_judicial_support: list[JudicialSupport]


class SafeResponse(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["ACCEPT", "CONTEST", "PARTIALLY_ACCEPT"]
    facts_evidence_quotes: list[str]


class PublicIssue(Structured):
    issue_id: str = Field(pattern=r"^I[1-9][0-9]{0,5}$")
    issue_text: str = Field(min_length=10)
    explain: str = Field(min_length=20, max_length=2000)


class JudgeCandidate(Structured):
    issues: list[PublicIssue]
    responses_to_feedback: list[SafeResponse]


class Feedback(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    issue_ids: list[IssueId]
    error_code: ErrorCode
    action: Literal["REVISE", "REMOVE", "ADD", "SPLIT", "RECONSIDER"]
    facts_evidence_quotes: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1, max_length=1500)


class SafeFeedback(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    issue_ids: list[IssueId]
    error_code: ErrorCode
    action: Literal["REVISE", "REMOVE", "ADD", "SPLIT", "RECONSIDER"]
    facts_evidence_quotes: list[str]


class RebuttalAssessment(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["WITHDRAW", "UPHOLD", "PARTIALLY_WITHDRAW"]
    explanation: str = Field(min_length=1, max_length=1500)
    facts_evidence_quotes: list[str] = Field(min_length=1)


class SafeAssessment(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["WITHDRAW", "UPHOLD", "PARTIALLY_WITHDRAW"]
    facts_evidence_quotes: list[str]


class SafeHistory(Structured):
    feedback: list[SafeFeedback]
    responses: list[SafeResponse]
    assessments: list[SafeAssessment]


class IssueReview(Structured):
    issue_id: IssueId
    classification: Literal["CORE", "SUPPORTING_FACT", "IRRELEVANT", "DUPLICATE"]
    related_issue_ids: list[IssueId]
    verdict: Literal["PASS", "REVISE", "REMOVE", "NEEDS_REVIEW"]
    error_codes: list[ErrorCode]
    explanation: str = Field(min_length=1, max_length=1500)
    facts_evidence_quotes: list[str] = Field(min_length=1)


class EvaluationRubric(Structured):
    grounding: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    legal_relevance: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    coverage: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    independence: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    format: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    explanation_quality: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    consistency: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    deduplication: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    explanation: str = Field(min_length=1, max_length=1500)


class CoverageItem(Structured):
    coverage_id: str = Field(pattern=r"^C[1-9][0-9]{0,5}$")
    issue_text: str = Field(min_length=10)
    facts_evidence_quotes: list[str] = Field(min_length=1)
    matched_issue_ids: list[str]


class BlindComparison(Structured):
    discovery_issue_id: str
    disposition: Literal["MATCHED", "MISSING", "EXCLUDED", "NEEDS_REVIEW"]
    coverage_issue_ids: list[str]
    matched_issue_ids: list[str]
    facts_evidence_quotes: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1, max_length=1500)


class JudgeOutput(Structured):
    per_issue_reviews: list[IssueReview]
    rubric: EvaluationRubric
    coverage_analysis: list[CoverageItem]
    blind_comparison: list[BlindComparison]
    error_codes: list[ErrorCode]
    feedback: str = Field(max_length=1500)
    generator_visible_feedback: list[Feedback]
    rebuttal_assessments: list[RebuttalAssessment]
    overall_verdict: Literal["PASS", "REVISE", "NEEDS_REVIEW"]
    unresolved_disputes: list[str]


class DiscoveryIssue(Structured):
    issue_id: str = Field(pattern=r"^D[1-9][0-9]{0,5}$")
    issue_text: str = Field(min_length=10)
    facts_evidence_quotes: list[str] = Field(min_length=1)


class DiscoveryOutput(Structured):
    issues: list[DiscoveryIssue]


class FewShotIssueCheck(Structured):
    example_id: str
    issue_index: int = Field(ge=0)
    issue_supported: bool
    explain_supported: bool
    facts_evidence_quotes: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1, max_length=1500)


class FewShotValidation(Structured):
    checks: list[FewShotIssueCheck]
