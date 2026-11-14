from __future__ import annotations
from ..config import digest
from ..schemas import GeneratorOutput, JudgeOutput
from ..validators.judge_validator import atomic_reviews


class StagnationDetector:
    """Detect repeated candidates/arguments; grounding remains a Judge assessment."""
    def __init__(self, threshold: int):
        self.threshold = threshold
        self.signatures: list[str] = []
        self.no_progress = 0
        self.signals: list[str] = []

    def observe(self, candidate: GeneratorOutput, judge: JudgeOutput) -> bool:
        signature = digest({"issues": sorted((i.issue_text, i.explain, i.focus_group, i.focus, i.subject_action, i.decisive_fact) for i in candidate.issues),
                            "feedback": sorted((tuple(f.issue_ids), f.error_code.value, f.action, f.failed_criterion, f.problem, f.reason, f.requested_change, tuple((r.issue_id, r.criterion) for r in f.criterion_refs), tuple(f.coverage_ids), tuple(f.cross_issue_ids)) for f in judge.generator_visible_feedback),
                            "rebuttal": sorted((r.feedback_id, r.decision, r.facts_argument) for r in candidate.responses_to_feedback),
                            "assessments": sorted((a.feedback_id, a.decision, a.explanation) for a in judge.rebuttal_assessments),
                            "private_scope": sorted((s.issue_id, s.judicial_relevance_confirmed, s.conclusion_consistent) for s in candidate.private_judicial_support),
                            "criteria": [[(path, c.status) for path,c in atomic_reviews(r)] for r in judge.per_issue_reviews],
                            "cross_issue": judge.cross_issue_evaluation.model_dump(mode="json"),
                            "verdict": judge.overall_verdict})
        signals = []
        if signature in self.signatures:
            signals.append("REPEATED_CANDIDATE_AND_ARGUMENTS")
        if len(self.signatures) >= 2 and signature == self.signatures[-2] and signature != self.signatures[-1]:
            signals.append("OSCILLATION")
        self.no_progress = self.no_progress+1 if signals else 0
        self.signatures.append(signature)
        self.signals.extend(signals)
        return self.no_progress >= self.threshold
