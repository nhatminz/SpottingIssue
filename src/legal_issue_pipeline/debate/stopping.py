from __future__ import annotations
from ..config import digest
from ..schemas import GeneratorOutput, JudgeOutput


class StagnationDetector:
    """Detect repeated *arguments with evidence*, not semantic equivalence by strings."""
    def __init__(self, threshold: int):
        self.threshold = threshold
        self.signatures: list[str] = []
        self.previous_evidence: set[str] = set()
        self.previous_count = 0
        self.previous_verdict: str | None = None
        self.no_progress = 0
        self.signals: list[str] = []

    def observe(self, candidate: GeneratorOutput, judge: JudgeOutput) -> bool:
        evidence = {q for i in candidate.issues for q in i.facts_evidence_quotes}
        evidence |= {q for f in judge.generator_visible_feedback for q in f.facts_evidence_quotes}
        signature = digest({"issues": sorted((i.focus_group, i.focus, i.subject_action, i.decisive_fact, i.explain,
                                              sorted(i.facts_evidence_quotes)) for i in candidate.issues),
                            "feedback": sorted((f.error_code.value, f.action, sorted(f.facts_evidence_quotes)) for f in judge.generator_visible_feedback),
                            "rebuttal": sorted((r.decision, sorted(r.facts_evidence_quotes)) for r in candidate.responses_to_feedback),
                            "assessments": sorted((a.decision, sorted(a.facts_evidence_quotes)) for a in judge.rebuttal_assessments),
                            "verdict": judge.overall_verdict})
        signals = []
        if signature in self.signatures:
            signals.append("REPEATED_EVIDENCE_AND_ARGUMENT_STRUCTURE")
        if len(self.signatures) >= 2 and signature == self.signatures[-2] and signature != self.signatures[-1]:
            signals.append("OSCILLATION")
        if self.signatures and len(candidate.issues) > self.previous_count and evidence <= self.previous_evidence:
            signals.append("ISSUE_GROWTH_WITHOUT_NEW_EVIDENCE")
        if self.previous_verdict and judge.overall_verdict != self.previous_verdict and evidence <= self.previous_evidence:
            signals.append("JUDGE_VERDICT_CHANGED_WITHOUT_NEW_EVIDENCE")
        self.no_progress = self.no_progress+1 if signals else 0
        self.signatures.append(signature)
        self.previous_evidence |= evidence
        self.previous_count = len(candidate.issues)
        self.previous_verdict = judge.overall_verdict
        self.signals.extend(signals)
        return self.no_progress >= self.threshold
