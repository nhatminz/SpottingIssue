"""The Judge API cannot receive an input record or Generator private metadata."""
from __future__ import annotations
from ..schemas import (DiscoveryOutput, GeneratorOutput, JudgeOutput, JudgeCandidate, PublicIssue,
                       SafeResponse, SafeAssessment, SafeFeedback, SafeHistory)
from .base_agent import BaseAgent


def public_candidate(candidate: GeneratorOutput, facts_clean: str) -> JudgeCandidate:
    if type(candidate) is not GeneratorOutput or not isinstance(facts_clean, str):
        raise TypeError("Public candidate projection requires GeneratorOutput and facts_clean")
    responses = [SafeResponse(feedback_id=r.feedback_id, decision=r.decision, facts_argument=r.facts_argument)
                 for r in candidate.responses_to_feedback]
    # This explicit construction is the only Generator -> Judge projection.
    return JudgeCandidate(issues=[PublicIssue(issue_id=i.issue_id, issue_text=i.issue_text, explain=i.explain)
                                  for i in candidate.issues], responses_to_feedback=responses)


class FeedbackFirewall:
    @staticmethod
    def project(judgment: JudgeOutput, facts_clean: str, current: JudgeCandidate):
        if type(judgment) is not JudgeOutput or not isinstance(facts_clean, str):
            raise TypeError("Feedback projection requires a facts-only JudgeOutput")
        ids = {i.issue_id for i in current.issues} if current is not None else None
        feedback, assessments = [], []
        for f in judgment.generator_visible_feedback:
            if ids is not None and set(f.issue_ids)-ids:
                raise ValueError("Feedback refers to an unknown issue ID")
            feedback.append(SafeFeedback(feedback_id=f.feedback_id, issue_ids=f.issue_ids,
                error_code=f.error_code, action=f.action, failed_criterion=f.failed_criterion,
                criterion_refs=f.criterion_refs, coverage_ids=f.coverage_ids, cross_issue_ids=f.cross_issue_ids,
                problem=f.problem, reason=f.reason, requested_change=f.requested_change))
        for a in judgment.rebuttal_assessments:
            assessments.append(SafeAssessment(feedback_id=a.feedback_id, decision=a.decision,
                                               explanation=a.explanation))
        return feedback, assessments


def valid_feedback_id(value: str) -> bool:
    import re
    return re.fullmatch(r"F[1-9][0-9]{0,5}", value) is not None


class JudgeAgent(BaseAgent):
    def __init__(self, client, config):
        super().__init__(client, config, "judge_system.md")
        self.reconsideration_prompt = (config.prompt_dir/"judge_reconsideration.md").read_text(encoding="utf-8")
        self.blind_system_prompt = (config.prompt_dir/"judge_blind_discovery.md").read_text(encoding="utf-8")

    async def discover(self, facts_clean: str) -> DiscoveryOutput:
        if not isinstance(facts_clean, str):
            raise TypeError("Blind discovery accepts only the facts_clean string")
        def validate(output):
            ids = [i.issue_id for i in output.issues]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate discovery ID")
        return await self.infer({"facts_clean": facts_clean}, DiscoveryOutput, validate=validate,
                                system_prompt_override=self.blind_system_prompt)

    async def evaluate(self, facts_clean: str, current: JudgeCandidate, previous: JudgeOutput | None,
                       discovery: DiscoveryOutput | None, history: list[SafeHistory]) -> JudgeOutput:
        if not isinstance(facts_clean, str) or type(current) is not JudgeCandidate:
            raise TypeError("Judge accepts only facts_clean and a projected JudgeCandidate; never a full record")
        if previous is not None and type(previous) is not JudgeOutput:
            raise TypeError("Invalid previous judgment")
        if any(type(h) is not SafeHistory for h in history):
            raise TypeError("Judge history must be facts-only SafeHistory objects")
        if discovery is not None and type(discovery) is not DiscoveryOutput:
            raise TypeError("Invalid blind discovery")
        if self.config.enable_blind_judge_discovery and discovery is None:
            raise ValueError("Evaluation requires the completed facts-only discovery")
        prior = None
        if previous is not None:
            safe_f, safe_a = FeedbackFirewall.project(previous, facts_clean, None)
            # Only Judge-authored feedback and public facts-based arguments
            # enter history. Generator's private scope notes never cross here.
            prior = {"overall_verdict": previous.overall_verdict,
                     "feedback": [f.model_dump(mode="json") for f in safe_f],
                     "assessments": [a.model_dump(mode="json") for a in safe_a]}
        payload = {"facts_clean": facts_clean, "current_candidate": current.model_dump(mode="json"),
                   "previous_judgment": prior,
                   "blind_discovery": discovery.model_dump(mode="json") if discovery else None,
                   "debate_history": [h.model_dump(mode="json") for h in history]}
        return await self.infer(payload, JudgeOutput, self.reconsideration_prompt if previous else "",
            validate=lambda output: self.validate_judgment(output, facts_clean, current, previous, discovery))

    def validate_judgment(self, output: JudgeOutput, facts_clean: str, current: JudgeCandidate,
                         previous: JudgeOutput | None, discovery: DiscoveryOutput | None = None):
        validate_structure(output, current, discovery)
        FeedbackFirewall.project(output, facts_clean, current)
        # Semantic FAIL, UNCERTAIN and contradictory PASS stay in debate/audit.
        # Never request JSON repair to change these legal assessments.


def validate_structure(output: JudgeOutput, current: JudgeCandidate | None = None,
                       discovery: DiscoveryOutput | None = None):
    """Only shape/identifier integrity errors belong in structured JSON repair."""
    reviews = [r.issue_id for r in output.per_issue_reviews]
    ids = set(reviews)
    if len(ids) != len(reviews) or (current is not None and ids != {i.issue_id for i in current.issues}):
        raise ValueError("Review every issue/explain pair exactly once")
    feedback_ids = [f.feedback_id for f in output.generator_visible_feedback]
    if len(feedback_ids) != len(set(feedback_ids)):
        raise ValueError("Duplicate feedback ID")
    for review in output.per_issue_reviews:
        if set(review.related_issue_ids)-(ids-{review.issue_id}):
            raise ValueError("Unknown related issue ID")
    core_ids = {r.issue_id for r in output.per_issue_reviews if r.classification == 'CORE'}
    coverage = {c.coverage_id: c for c in output.coverage_analysis}
    if len(coverage) != len(output.coverage_analysis):
        raise ValueError("Duplicate coverage ID")
    for item in coverage.values():
        if set(item.matched_issue_ids)-core_ids or len(item.matched_issue_ids) != len(set(item.matched_issue_ids)):
            raise ValueError("Coverage may match only distinct current CORE IDs")
    findings = {f.finding_id:f for f in output.cross_issue_evaluation.findings}
    if len(findings) != len(output.cross_issue_evaluation.findings):
        raise ValueError("Duplicate cross-issue finding ID")
    for finding in findings.values():
        if set(finding.issue_ids)-ids or len(set(finding.issue_ids)) != len(finding.issue_ids):
            raise ValueError("Cross-issue finding has invalid issue references")
    for feedback in output.generator_visible_feedback:
        if set(feedback.issue_ids)-ids or set(feedback.coverage_ids)-coverage.keys() or set(feedback.cross_issue_ids)-findings.keys():
            raise ValueError("Feedback has unknown issue, coverage or finding reference")
        if len(feedback.issue_ids) != len(set(feedback.issue_ids)):
            raise ValueError("Feedback has duplicate issue references")
        if any(ref.issue_id not in feedback.issue_ids for ref in feedback.criterion_refs):
            raise ValueError("Grouped criterion reference must belong to feedback issue_ids")
    comparisons = [c.discovery_issue_id for c in output.blind_comparison]
    if len(comparisons) != len(set(comparisons)):
        raise ValueError("Duplicate blind comparison")
    if discovery is not None and set(comparisons) != {d.issue_id for d in discovery.issues}:
        raise ValueError("Compare every blind proposal exactly once")
    if current is not None and discovery is None and comparisons:
        raise ValueError("Blind comparisons require discovery input")
    for comparison in output.blind_comparison:
        refs, matches = set(comparison.coverage_issue_ids), set(comparison.matched_issue_ids)
        if refs-coverage.keys() or matches-core_ids:
            raise ValueError("Unknown blind comparison reference")
        if comparison.disposition == "MATCHED":
            covered = set().union(*(set(coverage[key].matched_issue_ids) for key in refs))
            if not refs or not matches or not matches <= covered:
                raise ValueError("MATCHED requires current coverage matches")
        if comparison.disposition == "MISSING" and (not refs or matches or any(coverage[key].matched_issue_ids for key in refs)):
            raise ValueError("MISSING requires an unmatched coverage item")
    assessments = [a.feedback_id for a in output.rebuttal_assessments]
    if len(assessments) != len(set(assessments)):
        raise ValueError("Duplicate rebuttal assessment")
    if current is not None and set(assessments) != {r.feedback_id for r in current.responses_to_feedback}:
        raise ValueError("Reconsider every Generator response exactly once")
