from __future__ import annotations
from ..schemas import DiscoveryOutput, GeneratorOutput, JudgeOutput, SafeAssessment, SafeFeedback
from ..validators.evidence_validator import validate_quotes
from .base_agent import BaseAgent


class FeedbackFirewall:
    """Allowlist projection, not redaction of arbitrary prose.

    No narrative, suggested issue text, markdown quote or private audit can cross.
    Only known enums, existing issue IDs, feedback IDs and exact situation spans.
    """
    @staticmethod
    def project(judgment: JudgeOutput, situation: str, current: GeneratorOutput) -> tuple[list[SafeFeedback], list[SafeAssessment]]:
        allowed_ids = {i.issue_id for i in current.issues}
        safe = []
        for f in judgment.generator_visible_feedback:
            validate_quotes(f.situation_evidence_quotes, situation, "visible feedback")
            if set(f.issue_ids) - allowed_ids:
                raise ValueError("Feedback refers to an unknown issue ID")
            # Feedback IDs are generated locally: arbitrary strings from Judge
            # could themselves encode a private fact. Preserve only validated IDs.
            if not valid_feedback_id(f.feedback_id):
                raise ValueError("feedback_id must match F plus digits")
            safe.append(SafeFeedback(feedback_id=f.feedback_id, issue_ids=f.issue_ids,
                                     error_code=f.error_code, action=f.action,
                                     situation_evidence_quotes=f.situation_evidence_quotes))
        assessments = []
        for a in judgment.rebuttal_assessments:
            validate_quotes(a.situation_evidence_quotes, situation, "rebuttal assessment")
            if not valid_feedback_id(a.feedback_id):
                raise ValueError("Invalid assessment feedback ID")
            assessments.append(SafeAssessment(feedback_id=a.feedback_id, decision=a.decision,
                                              situation_evidence_quotes=a.situation_evidence_quotes))
        return safe, assessments


def valid_feedback_id(value: str) -> bool:
    import re
    return re.fullmatch(r"F[0-9]{1,9}", value) is not None


class JudgeAgent(BaseAgent):
    def __init__(self, client, config):
        super().__init__(client, config, "judge_system.md")
        self.reconsideration_prompt = (config.prompt_dir/"judge_reconsideration.md").read_text(encoding="utf-8")

    @staticmethod
    def sources(record: dict) -> dict:
        return {k: record.get(k, [] if k.startswith("citations") else "") for k in ["situation", "markdown", "citations_law", "citations"]}

    async def discover(self, record: dict) -> DiscoveryOutput:
        def validate(output):
            for issue in output.issues:
                validate_quotes(issue.situation_evidence_quotes, record["situation"], "blind discovery")
        return await self.infer({**self.sources(record), "task": "BLIND_DISCOVERY: independently discover situation-supported issues, without seeing Generator output"}, DiscoveryOutput, validate=validate)

    async def evaluate(self, record: dict, current: GeneratorOutput, previous: JudgeOutput | None,
                       discovery: DiscoveryOutput | None, mechanical_errors: list[str], debate_history: list[dict]) -> JudgeOutput:
        payload = {**self.sources(record), "current_candidate": current.model_dump(mode="json"),
                   "previous_judgment": previous.model_dump(mode="json") if previous else None,
                   "blind_discovery": discovery.model_dump(mode="json") if discovery else None,
                   "mechanical_errors": mechanical_errors, "structured_debate_history": debate_history,
                   "coverage_check_enabled": self.config.enable_coverage_check,
                   "situation_audit_enabled": self.config.enable_situation_audit,
                   "situation_error_policy": self.config.situation_error_policy}
        return await self.infer(payload, JudgeOutput, self.reconsideration_prompt if previous else "",
                                validate=lambda output: self.validate_judgment(output, record, current, previous))

    def validate_judgment(self, output: JudgeOutput, record: dict, current: GeneratorOutput, previous: JudgeOutput | None) -> None:
        ids = {i.issue_id for i in current.issues}
        reviews = [r.issue_id for r in output.per_issue_reviews]
        if set(reviews) != ids or len(reviews) != len(ids):
            raise ValueError("Review every current issue exactly once")
        feedback_ids = [f.feedback_id for f in output.generator_visible_feedback]
        if len(set(feedback_ids)) != len(feedback_ids):
            raise ValueError("Duplicate feedback ID")
        for review in output.per_issue_reviews:
            validate_quotes(review.situation_evidence_quotes, record["situation"], "issue review")
            if review.verdict == "PASS" and review.error_codes:
                raise ValueError("Passing issue cannot have error codes")
        for issue in output.suggested_missing_issues:
            validate_quotes(issue.situation_evidence_quotes, record["situation"], "missing issue")
        for finding in output.situation_audit.missing_facts + output.situation_audit.contradictions:
            validate_quotes(finding.markdown_evidence_quotes, record["markdown"], "situation audit")
        FeedbackFirewall.project(output, record["situation"], current)
        if previous and self.config.enable_judge_reconsideration:
            expected = {r.feedback_id for r in current.responses_to_feedback}
            actual = [a.feedback_id for a in output.rebuttal_assessments]
            if set(actual) != expected or len(actual) != len(expected):
                raise ValueError("Reconsider each Generator response exactly once")
        if output.overall_verdict == "PASS":
            if (output.error_codes or output.generator_visible_feedback or output.suggested_missing_issues
                or output.unresolved_disputes or any(r.verdict != "PASS" or r.error_codes for r in output.per_issue_reviews)):
                raise ValueError("PASS contradicts unresolved errors, coverage gaps, or disputes")
        elif not output.generator_visible_feedback and not output.situation_audit.needs_review and not output.unresolved_disputes:
            raise ValueError("Non-PASS requires actionable feedback or explicit uncertainty/dispute")


def situation_error(judgment: JudgeOutput, policy: str) -> bool:
    audit = judgment.situation_audit
    missing = any(f.material and not f.equivalent_in_situation for f in audit.missing_facts)
    contradiction = any(f.material for f in audit.contradictions)
    return missing or (policy == "material_missing_or_contradiction" and contradiction)
