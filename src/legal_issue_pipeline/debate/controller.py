from __future__ import annotations
import time
from ..agents.generator import GeneratorAgent
from ..agents.judge import FeedbackFirewall, JudgeAgent, situation_error
from ..config import PipelineConfig
from ..llm.base_client import LLMError
from ..schemas import GeneratorOutput
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
        return (not candidate.errors and not candidate.judgment.situation_audit.needs_review
                and self.config.enable_coverage_check and self.config.enable_situation_audit
                and self.config.enable_evidence_validation and self.config.strict_format
                and self.config.enable_deduplication and self.config.enable_judge_reconsideration
                and self.config.enable_generator_rebuttal)

    def _approved(self, candidate: EvaluatedCandidate) -> bool:
        # situation_error is deliberately independent of the acceptance gate.
        return (self._required_validations_passed(candidate)
                and candidate.judgment.overall_verdict == "PASS"
                and scope_rubric_passes(candidate.judgment)
                and not candidate.judgment.unresolved_disputes)

    def _select(self, candidates: list[EvaluatedCandidate]) -> EvaluatedCandidate:
        if candidates and self._approved(candidates[-1]):
            # With early-stop disabled, prefer the final fully verified revision
            # over an older PASS that merely carries longer evidence quotes.
            return candidates[-1]
        valid = [c for c in candidates if not c.errors]
        if not valid:
            raise LLMError("No mechanically valid, evaluated candidate; record failed, no labels emitted")
        if self.config.finalize_policy == "last_valid":
            return valid[-1]
        # Evidence-supported coverage, independent issue review, unresolved errors;
        # no automatic authority win. Ranking is a heuristic, never gold approval.
        def rank(c):
            q = {q for i in c.output.issues for q in i.situation_evidence_quotes}
            quote_chars = sum(len(x) for x in q)
            adverse = sum(len(r.error_codes) + (r.verdict != "PASS") for r in c.judgment.per_issue_reviews)
            return (self._approved(c), -adverse-len(c.judgment.unresolved_disputes)-len(c.judgment.suggested_missing_issues),
                    quote_chars, c.round_index)
        return max(valid, key=rank)

    async def run(self, record: dict) -> DebateResult:
        start = time.monotonic()
        discovery = await self.judge.discover(record["situation"]) if self.config.enable_blind_judge_discovery else None
        self.blind_discovery = discovery
        current = await self.generator.generate(record["situation"])
        previous = None
        candidates = []
        own_history: list[dict] = []
        explicit_history: list[dict] = []
        detector = StagnationDetector(self.config.max_stagnant_rounds)
        revisions = 0
        reason = "MAX_ROUNDS"
        early_stop = False
        # N rounds = N Judge -> Generator response cycles, plus a final Judge.
        for evaluation_index in range(self.config.max_debate_rounds+1):
            errors = candidate_errors(current, record["situation"], self.config)
            judgment = await self.judge.evaluate(record, current, previous, discovery, errors, explicit_history)
            candidate = EvaluatedCandidate(current, judgment, errors, revisions)
            candidates.append(candidate)
            entry = {"evaluation_index": evaluation_index, "completed_debate_rounds": revisions,
                     "generator": current.model_dump(mode="json"), "judge": judgment.model_dump(mode="json"),
                     "mechanical_errors": errors}
            self.trace.append(entry)
            stagnant = detector.observe(current, judgment)
            if self._approved(candidate) and self.config.enable_early_stop:
                reason, early_stop = "PASS", revisions < self.config.max_debate_rounds
                break
            if judgment.situation_audit.needs_review and not judgment.generator_visible_feedback:
                reason = "SITUATION_UNCERTAIN"
                break
            if evaluation_index == self.config.max_debate_rounds:
                break
            if stagnant and self.config.stop_on_stagnation:
                reason = "STAGNATION"
                break
            safe_feedback, safe_assessments = FeedbackFirewall.project(judgment, record["situation"], current)
            if not self.config.enable_judge_reconsideration:
                safe_assessments = []
            previous = judgment
            # Only safe feedback and Generator's own explicit prior responses.
            revised = await self.generator.revise(record["situation"], current, safe_feedback, safe_assessments, own_history)
            own_history.append({"feedback": [f.model_dump(mode="json") for f in safe_feedback],
                                "own_responses": [r.model_dump(mode="json") for r in revised.responses_to_feedback]})
            explicit_history.append({"feedback": [f.model_dump(mode="json") for f in safe_feedback],
                                     "generator_response": revised.model_dump(mode="json"),
                                     "judge_assessments": [a.model_dump(mode="json") for a in safe_assessments]})
            current = revised
            revisions += 1
        selected = self._select(candidates)
        # Any unresolved final disagreement survives selection of an older candidate.
        approved = self._approved(candidates[-1]) and selected is candidates[-1]
        if approved:
            reason = "PASS"
        final = candidates[-1]
        final_issues = [i.issue_text for i in final.output.issues]
        rejection_reasons = []
        if not approved:
            if final.judgment.overall_verdict != "PASS":
                rejection_reasons.append(f"Judge final verdict: {final.judgment.overall_verdict}")
            for criterion in RUBRIC_CRITERIA:
                value = getattr(final.judgment.rubric,criterion)
                if value != "PASS":
                    rejection_reasons.append(f"Rubric {criterion}: {value}")
            if not self._required_validations_passed(final):
                rejection_reasons.append("Required validation disabled, failed, or situation audit uncertain")
            rejection_reasons.extend(final.judgment.unresolved_disputes)
            rejection_reasons.extend(r.explanation for r in final.judgment.per_issue_reviews if r.verdict != "PASS")
            rejection_reasons.extend(f.explanation for f in final.judgment.generator_visible_feedback)
            if final.judgment.feedback.strip():
                rejection_reasons.append("Judge feedback: "+final.judgment.feedback)
            rejection_reasons = list(dict.fromkeys(rejection_reasons))
        # Rejection feedback is mandatory even if ordinary debate history is off.
        feedback_history = [{"evaluation_index":e["evaluation_index"],"rounds":e["completed_debate_rounds"],
                             "issues":[i["issue_text"] for i in e["generator"]["issues"]],
                             "responses_to_feedback":e["generator"]["responses_to_feedback"],
                             "judge":e["judge"],"mechanical_errors":e["mechanical_errors"]} for e in self.trace] if not approved else []
        audit = {"status": "COMPLETED" if approved else "REJECTED", "consensus": "PASS" if approved else "UNRESOLVED",
                 "stop_reason": reason, "rounds": revisions, "judge_evaluations": len(candidates),
                 "required_validations_passed":self._required_validations_passed(final),
                 "needs_review":not approved,"final_issues":final_issues,
                 "final_judge":final.judgment.model_dump(mode="json"),
                 "rejection_reasons":rejection_reasons,"feedback_history":feedback_history,
                 "selected_evaluation": candidates.index(selected), "early_stop": early_stop,
                 "stagnation_signals": detector.signals, "elapsed_seconds": time.monotonic()-start,
                 "generator_contests": sum(r.decision == "CONTEST" for c in candidates for r in c.output.responses_to_feedback),
                 "judge_changes": sum(a.decision != "UPHOLD" for c in candidates for a in c.judgment.rebuttal_assessments),
                 "selected_situation_audit": selected.judgment.situation_audit.model_dump(mode="json"),
                 "unresolved_disputes": candidates[-1].judgment.unresolved_disputes,
                 "selection_policy": self.config.finalize_policy,
                 "selection_is_heuristic": not approved,
                 "blind_discovery": discovery.model_dump(mode="json") if discovery else None,
                 "blind_comparison": final.judgment.model_dump(mode="json")["blind_comparison"],
                 "scope_rubric": final.judgment.rubric.model_dump(mode="json"),
                 "coverage_analysis": final.judgment.model_dump(mode="json")["coverage_analysis"],
                 "history": self.trace if self.config.save_debate_history else [],
                 "requests": {"generator": self.generator.request_metrics, "judge": self.judge.request_metrics}}
        # A best-valid candidate may be kept privately, but rejected exports must
        # describe the actual final revision and can never enter the main JSONL.
        return DebateResult(final_issues, situation_error(final.judgment, self.config.situation_error_policy),
                            CaseStatus.COMPLETED if approved else CaseStatus.REJECTED, audit)
