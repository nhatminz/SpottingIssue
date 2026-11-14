"""Separate full-judgment Generator output from the facts-only Judge contract."""
from __future__ import annotations
from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

IssueId = Annotated[str, Field(pattern=r"^I[1-9][0-9]{0,5}$")]
CONTRACT_VERSION = "fac_hierarchical_judge_v5"


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
    WRONG_SUBJECT = "WRONG_SUBJECT"
    FRAGMENTATION = "FRAGMENTATION"
    OVER_MERGING = "OVER_MERGING"
    AMBIGUOUS_FACT = "AMBIGUOUS_FACT"


class Issue(Structured):
    issue_id: IssueId
    issue_text: str = Field(min_length=10)
    explain: str = Field(min_length=20, max_length=2000)
    focus_group: Literal["LIABILITY", "VALIDITY", "DETERMINATION", "PROCEDURE"]
    focus: str = Field(min_length=1)
    subject_action: str = Field(min_length=1)
    decisive_fact: str = Field(min_length=1)


class JudicialSupport(Structured):
    issue_id: str = Field(pattern=r"^I[1-9][0-9]{0,5}$")
    judicial_relevance_confirmed: bool
    conclusion_consistent: bool
    explanation: str = Field(min_length=1, max_length=1500)


class FeedbackResponse(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["ACCEPT", "CONTEST", "PARTIALLY_ACCEPT"]
    # Public facts-based argument, unlike private_judicial_support.explanation.
    facts_argument: str = Field(min_length=1, max_length=1500)


class GeneratorOutput(Structured):
    issues: list[Issue]
    responses_to_feedback: list[FeedbackResponse]
    private_judicial_support: list[JudicialSupport]


class SafeResponse(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["ACCEPT", "CONTEST", "PARTIALLY_ACCEPT"]
    facts_argument: str = Field(min_length=1, max_length=1500)


class PublicIssue(Structured):
    issue_id: str = Field(pattern=r"^I[1-9][0-9]{0,5}$")
    issue_text: str = Field(min_length=10)
    explain: str = Field(min_length=20, max_length=2000)


class JudgeCandidate(Structured):
    issues: list[PublicIssue]
    responses_to_feedback: list[SafeResponse]


CriterionStatus = Literal["PASS", "FAIL", "UNCERTAIN"]
IssueCriterion = Literal[
    "factual_grounding.actor_grounding", "factual_grounding.conduct_grounding",
    "factual_grounding.object_grounding", "factual_grounding.decisive_fact_grounding",
    "factual_grounding.semantic_inference", "subject_liability.subject_precision",
    "subject_liability.conduct_attribution", "subject_liability.liability_precision",
    "subject_liability.subject_grouping", "atomicity.atomicity", "atomicity.independence",
    "atomicity.overlap", "atomicity.granularity", "explanation_review.factual_basis",
    "explanation_review.legal_connection", "explanation_review.issue_alignment",
]
FeedbackCriterion = Literal[
    "factual_grounding.actor_grounding", "factual_grounding.conduct_grounding",
    "factual_grounding.object_grounding", "factual_grounding.decisive_fact_grounding",
    "factual_grounding.semantic_inference", "subject_liability.subject_precision",
    "subject_liability.conduct_attribution", "subject_liability.liability_precision",
    "subject_liability.subject_grouping", "atomicity.atomicity", "atomicity.independence",
    "atomicity.overlap", "atomicity.granularity", "explanation_review.factual_basis",
    "explanation_review.legal_connection", "explanation_review.issue_alignment",
    "COVERAGE", "DEDUPLICATION", "FRAGMENTATION", "OVER_MERGING", "FORMAT", "LEGAL_RELEVANCE",
]


class CriterionReference(Structured):
    issue_id: IssueId
    criterion: IssueCriterion


class Feedback(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    issue_ids: list[IssueId]
    error_code: ErrorCode
    action: Literal["REVISE", "REMOVE", "ADD", "SPLIT", "RECONSIDER"]
    failed_criterion: FeedbackCriterion
    # Grouped feedback must explicitly identify every adverse criterion it handles.
    criterion_refs: list[CriterionReference] = Field(default_factory=list)
    coverage_ids: list[Annotated[str, Field(pattern=r"^C[1-9][0-9]{0,5}$")]] = Field(default_factory=list)
    cross_issue_ids: list[Annotated[str, Field(pattern=r"^X[1-9][0-9]{0,5}$")]] = Field(default_factory=list)
    problem: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=1500)
    requested_change: str = Field(min_length=1, max_length=1500)


class SafeFeedback(Feedback):
    """Same facts-only contract; no private fields or untyped extension channel."""


class RebuttalAssessment(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["WITHDRAW", "UPHOLD", "PARTIALLY_WITHDRAW"]
    explanation: str = Field(min_length=1, max_length=1500)


class SafeAssessment(Structured):
    feedback_id: str = Field(pattern=r"^F[1-9][0-9]{0,5}$")
    decision: Literal["WITHDRAW", "UPHOLD", "PARTIALLY_WITHDRAW"]
    explanation: str = Field(min_length=1, max_length=1500)


class SafeHistory(Structured):
    feedback: list[SafeFeedback]
    responses: list[SafeResponse]
    assessments: list[SafeAssessment]


class CriterionReview(Structured):
    status: CriterionStatus
    reason: str = Field(min_length=1, max_length=1000)


class GroundingCriterionReview(CriterionReview):
    basis: Literal["FACT", "SUPPORTED_INFERENCE", "UNSUPPORTED", "UNCERTAIN"]


class FactualGroundingReview(Structured):
    actor_grounding: GroundingCriterionReview
    conduct_grounding: GroundingCriterionReview
    object_grounding: GroundingCriterionReview
    decisive_fact_grounding: GroundingCriterionReview
    semantic_inference: GroundingCriterionReview


class SubjectLiabilityReview(Structured):
    subject_precision: CriterionReview
    conduct_attribution: CriterionReview
    liability_precision: CriterionReview
    subject_grouping: CriterionReview


class AtomicityReview(Structured):
    atomicity: CriterionReview
    independence: CriterionReview
    overlap: CriterionReview
    granularity: CriterionReview


class ExplanationReview(Structured):
    factual_basis: CriterionReview
    legal_connection: CriterionReview
    issue_alignment: CriterionReview


class IssueReview(Structured):
    issue_id: IssueId
    issue_supported: bool
    explain_supported: bool
    factual_grounding: FactualGroundingReview
    subject_liability: SubjectLiabilityReview
    atomicity: AtomicityReview
    explanation_review: ExplanationReview
    classification: Literal["CORE", "SUPPORTING_FACT", "IRRELEVANT", "DUPLICATE"]
    related_issue_ids: list[IssueId]
    verdict: Literal["PASS", "REVISE", "REMOVE", "NEEDS_REVIEW"]
    error_codes: list[ErrorCode]
    explanation: str = Field(min_length=1, max_length=1500)


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


class CoverageTests(Structured):
    facts_grounding: CriterionReview
    legal_relevance: CriterionReview
    independence: CriterionReview
    # PASS: semantic comparison establishes the stated matches, or confirms no match.
    existing_coverage: CriterionReview


class CoverageItem(Structured):
    coverage_id: str = Field(pattern=r"^C[1-9][0-9]{0,5}$")
    issue_text: str = Field(min_length=10)
    explanation: str = Field(min_length=1, max_length=1500)
    matched_issue_ids: list[str]
    tests: CoverageTests


class CrossIssueFinding(Structured):
    finding_id: str = Field(pattern=r"^X[1-9][0-9]{0,5}$")
    kind: Literal["DUPLICATE", "FRAGMENTATION", "OVER_MERGING"]
    issue_ids: list[IssueId] = Field(min_length=1)
    explanation: str = Field(min_length=1, max_length=1500)


class CrossIssueEvaluation(Structured):
    coverage: CriterionReview
    deduplication: CriterionReview
    fragmentation: CriterionReview
    over_merging: CriterionReview
    findings: list[CrossIssueFinding]


class BlindComparison(Structured):
    discovery_issue_id: str
    disposition: Literal["MATCHED", "MISSING", "EXCLUDED", "NEEDS_REVIEW"]
    coverage_issue_ids: list[str]
    matched_issue_ids: list[str]
    explanation: str = Field(min_length=1, max_length=1500)


class JudgeOutput(Structured):
    per_issue_reviews: list[IssueReview]
    rubric: EvaluationRubric
    coverage_analysis: list[CoverageItem]
    blind_comparison: list[BlindComparison]
    cross_issue_evaluation: CrossIssueEvaluation
    error_codes: list[ErrorCode]
    feedback: str = Field(max_length=1500)
    generator_visible_feedback: list[Feedback]
    rebuttal_assessments: list[RebuttalAssessment]
    overall_verdict: Literal["PASS", "REVISE", "NEEDS_REVIEW"]
    unresolved_disputes: list[str]


class DiscoveryIssue(Structured):
    issue_id: str = Field(pattern=r"^D[1-9][0-9]{0,5}$")
    issue_text: str = Field(min_length=10)
    explanation: str = Field(min_length=1, max_length=1500)


class DiscoveryOutput(Structured):
    issues: list[DiscoveryIssue]


class FewShotIssueCheck(Structured):
    example_id: str = Field(pattern=r"^E[1-5]$")
    issue_index: int = Field(ge=0)
    issue_supported: bool
    explain_supported: bool
    explanation: str = Field(min_length=1, max_length=1500)


class FewShotValidation(Structured):
    checks: list[FewShotIssueCheck]
