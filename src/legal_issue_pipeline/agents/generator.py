from __future__ import annotations
import json
import logging
from ..schemas import GeneratorOutput, SafeFeedback, SafeAssessment, SafeHistory, FewShotValidation, FewShotReview
from ..validators.evidence_validator import validate_quotes
from ..validators.format_validator import candidate_errors
from ..io.records import generator_sources
from ..io.fewshot import FewShotBank
from .base_agent import BaseAgent

log = logging.getLogger(__name__)


class GeneratorAgent(BaseAgent):
    def __init__(self, client, config, fewshot: FewShotBank | None = None):
        super().__init__(client, config, "generator_system.md")
        self.revision_prompt = (config.prompt_dir/"generator_revision.md").read_text(encoding="utf-8")
        self.fewshot = fewshot or FewShotBank(config.fewshot_path)
        self.excluded_examples: list[str] = []
        self.fewshot_review: dict | None = None

    async def validate_fewshot(self) -> FewShotValidation:
        # A Generator request, not a third role or a Judge request. Unapproved
        # examples are data to audit, never reference demonstrations yet.
        system = (self.config.prompt_dir/"generator_fewshot_validation.md").read_text(encoding="utf-8")
        report = None
        def validate(review):
            nonlocal report
            self.fewshot_review = review.model_dump(mode="json")
            report = self.fewshot.resolve_review(review)
        await self.infer({"examples_to_audit": self.fewshot.validation_examples()}, FewShotReview,
                         validate=validate, system_prompt_override=system)
        if report is None:
            raise AssertionError("Few-shot review returned without validation")
        return report

    def _payload(self, record):
        examples, excluded = self.fewshot.for_record(record)
        self.excluded_examples = excluded
        if excluded:
            log.warning("Generator excluded matching few-shot examples %s to prevent answer leakage", excluded)
        return {**generator_sources(record), "few_shot_examples": examples}

    async def generate(self, record: dict) -> GeneratorOutput:
        payload = self._payload(record)
        return await self.infer(payload, GeneratorOutput,
            validate=lambda output: self._validate_responses(output, [], record))

    async def revise(self, record: dict, previous: GeneratorOutput, feedback: list[SafeFeedback],
                     assessments: list[SafeAssessment], own_history: list[SafeHistory]) -> GeneratorOutput:
        if any(type(f) is not SafeFeedback for f in feedback) or any(type(a) is not SafeAssessment for a in assessments):
            raise TypeError("Generator requires firewall-approved feedback/assessments")
        if any(type(h) is not SafeHistory for h in own_history):
            raise TypeError("Only typed safe debate history is permitted")
        payload = {**self._payload(record), "previous_candidate": previous.model_dump(mode="json"),
                   "feedback": [f.model_dump(mode="json") for f in feedback],
                   "rebuttal_assessments": [a.model_dump(mode="json") for a in assessments],
                   "own_debate_history": [h.model_dump(mode="json") for h in own_history],
                   "allow_contest": self.config.enable_generator_rebuttal}
        return await self.infer(payload, GeneratorOutput, self.revision_prompt,
                               validate=lambda output: self._validate_responses(output, feedback, record))

    def _validate_responses(self, output, feedback, record):
        facts = record["benchmark_seed"]["facts_clean"]
        errors = candidate_errors(output, facts, self.config)
        if errors:
            raise ValueError("Generator candidate must be repaired: "+"; ".join(errors))
        ids = {i.issue_id for i in output.issues}
        supports = [s.issue_id for s in output.private_judicial_support]
        if set(supports) != ids or len(supports) != len(ids):
            raise ValueError("Every issue needs exactly one private judicial support entry")
        for support in output.private_judicial_support:
            validate_quotes(support.application_evidence_quotes, record["benchmark_seed"]["application"], "Generator application scope")
            validate_quotes(support.conclusion_evidence_quotes, record["benchmark_seed"]["conclusion"], "Generator conclusion scope")
            if not support.judicial_relevance_confirmed or not support.conclusion_consistent:
                raise ValueError("Do not retain an issue not independently resolved and conclusion-consistent")
        # Prevent verbatim private judicial evidence from being copied into the
        # public pair; semantic support of paraphrases is the facts-only Judge's task.
        public = "\n".join(text for i in output.issues for text in (i.issue_text, i.explain))
        for support in output.private_judicial_support:
            for quote in support.application_evidence_quotes + support.conclusion_evidence_quotes:
                if quote not in facts and quote in public:
                    raise ValueError("Private judicial evidence copied into public issue/explain")
        expected = {f.feedback_id for f in feedback}
        actual = [r.feedback_id for r in output.responses_to_feedback]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("Respond exactly once to every current feedback_id")
        for response in output.responses_to_feedback:
            if response.decision == "CONTEST" and not self.config.enable_generator_rebuttal:
                raise ValueError("Contesting disabled by configuration")
            validate_quotes(response.facts_evidence_quotes, facts, "generator rebuttal", required=response.decision != "ACCEPT")
