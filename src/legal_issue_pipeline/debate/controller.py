from __future__ import annotations
import time
from ..agents.generator import GeneratorAgent
from ..agents.judge import FeedbackFirewall, JudgeAgent, public_candidate
from ..config import PipelineConfig
from ..llm.base_client import LLMError
from ..schemas import SafeHistory
from ..validators.format_validator import candidate_errors
from ..validators.judge_validator import scope_rubric_passes, RUBRIC_CRITERIA
from .state import CaseStatus, DebateResult, EvaluatedCandidate
from .stopping import StagnationDetector


class DebateController:
    def __init__(self, generator: GeneratorAgent, judge: JudgeAgent, config: PipelineConfig):
        self.generator, self.judge, self.config = generator, judge, config
        self.trace: list[dict] = []
        self.blind_discovery = None

    def _required_validations_passed(self, candidate: EvaluatedCandidate) -> bool:
        return (not candidate.errors and self.config.enable_coverage_check
                and self.config.enable_evidence_validation and self.config.strict_format
                and self.config.enable_deduplication and self.config.enable_judge_reconsideration
                and self.config.enable_generator_rebuttal)

    def _approved(self, candidate: EvaluatedCandidate) -> bool:
        return self._required_validations_passed(candidate) and scope_rubric_passes(candidate.judgment)

    def _select(self, candidates: list[EvaluatedCandidate]) -> EvaluatedCandidate:
        if candidates and self._approved(candidates[-1]):
            return candidates[-1]
        valid = [c for c in candidates if not c.errors]
        if not valid:
            raise LLMError("No mechanically valid, evaluated candidate; no labels emitted")
        if self.config.finalize_policy == "last_valid":
            return valid[-1]
        def rank(candidate):
            adverse = sum(len(r.error_codes) + (r.verdict != "PASS") for r in candidate.judgment.per_issue_reviews)
            return (self._approved(candidate), -adverse-len(candidate.judgment.unresolved_disputes), candidate.round_index)
        return max(valid, key=rank)

    async def run(self, record: dict) -> DebateResult:
        start = time.monotonic()
        facts = record["benchmark_seed"]["facts_clean"]
        current = await self.generator.generate(record)
        discovery = await self.judge.discover(facts) if self.config.enable_blind_judge_discovery else None
        self.blind_discovery = discovery
        previous, candidates, history = None, [], []
        detector = StagnationDetector(self.config.max_stagnant_rounds)
        revisions, reason, early_stop = 0, "MAX_ROUNDS", False
        # Six Judge -> Generator cycles at most; evaluation 6 verifies revision 6.
        for evaluation_index in range(self.config.max_debate_rounds+1):
            errors = candidate_errors(current, facts, self.config)
            public = public_candidate(current, facts)
            judgment = await self.judge.evaluate(facts, public, previous, discovery, history)
            candidate = EvaluatedCandidate(current, judgment, errors, revisions)
            candidates.append(candidate)
            self.trace.append({"evaluation_index": evaluation_index, "completed_debate_rounds": revisions,
                "generator": current.model_dump(mode="json"), "judge": judgment.model_dump(mode="json"),
                "mechanical_errors": errors})
            stagnant = detector.observe(current, judgment)
            if self._approved(candidate) and self.config.enable_early_stop:
                reason, early_stop = "PASS", revisions < self.config.max_debate_rounds
                break
            if judgment.overall_verdict == "NEEDS_REVIEW" and not judgment.generator_visible_feedback:
                reason = "FACTS_UNCERTAIN"
                break
            if evaluation_index == self.config.max_debate_rounds:
                break
            if stagnant and self.config.stop_on_stagnation:
                reason = "STAGNATION"
                break
            feedback, assessments = FeedbackFirewall.project(judgment, facts, public)
            revised = await self.generator.revise(record, current, feedback, assessments, history)
            # Neither full Generator output nor private judicial evidence crosses here.
            safe_revised = public_candidate(revised, facts)
            history.append(SafeHistory(feedback=feedback, responses=safe_revised.responses_to_feedback, assessments=assessments))
            previous, current = judgment, revised
            revisions += 1
        selected = self._select(candidates)
        final = candidates[-1]
        approved = selected is final and self._approved(final)
        issues = [i.issue_text for i in final.output.issues]
        explains = [i.explain for i in final.output.issues]
        rejection_reasons = []
        if approved:
            reason = "PASS"
        else:
            rejection_reasons.append("Judge final verdict: "+final.judgment.overall_verdict)
            rejection_reasons += [f"Rubric {key}: {getattr(final.judgment.rubric,key)}" for key in RUBRIC_CRITERIA
                                  if getattr(final.judgment.rubric,key) != "PASS"]
            if not self._required_validations_passed(final):
                rejection_reasons.append("A required validation was disabled or failed")
            rejection_reasons += final.judgment.unresolved_disputes
            rejection_reasons += [r.explanation for r in final.judgment.per_issue_reviews if r.verdict != "PASS"]
            rejection_reasons += [f.explanation for f in final.judgment.generator_visible_feedback]
            rejection_reasons = list(dict.fromkeys(rejection_reasons))
        audit = {"contract": "fac_facts_only_v3", "status": "COMPLETED" if approved else "REJECTED",
            "consensus": "PASS" if approved else "UNRESOLVED", "stop_reason": reason, "rounds": revisions,
            "judge_evaluations": len(candidates), "required_validations_passed": self._required_validations_passed(final),
            "needs_review": not approved, "final_issues": issues, "final_explain": explains,
            "final_generator": final.output.model_dump(mode="json"), "final_judge": final.judgment.model_dump(mode="json"),
            "rejection_reasons": rejection_reasons, "feedback_history": self.trace if not approved else [],
            "selected_evaluation": candidates.index(selected), "selection_policy": self.config.finalize_policy,
            "selection_is_heuristic": not approved, "early_stop": early_stop, "stagnation_signals": detector.signals,
            "elapsed_seconds": time.monotonic()-start,
            "generator_contests": sum(r.decision == "CONTEST" for c in candidates for r in c.output.responses_to_feedback),
            "judge_changes": sum(a.decision != "UPHOLD" for c in candidates for a in c.judgment.rebuttal_assessments),
            "blind_discovery": discovery.model_dump(mode="json") if discovery else None,
            "blind_comparison": final.judgment.model_dump(mode="json")["blind_comparison"],
            "scope_rubric": final.judgment.rubric.model_dump(mode="json"),
            "coverage_analysis": final.judgment.model_dump(mode="json")["coverage_analysis"],
            "excluded_fewshot_examples": self.generator.excluded_examples,
            "fewshot_count": len(self.generator.fewshot.examples)-len(self.generator.excluded_examples),
            "history": self.trace if self.config.save_debate_history else [],
            "requests": {"generator": self.generator.request_metrics, "judge": self.judge.request_metrics}}
        return DebateResult(issues, explains, CaseStatus.COMPLETED if approved else CaseStatus.REJECTED, audit)
