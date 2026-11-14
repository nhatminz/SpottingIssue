from __future__ import annotations
import logging
from ..schemas import GeneratorOutput, SafeFeedback, SafeAssessment, SafeHistory, FewShotValidation
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
        def validate(review):
            self.fewshot_review = review.model_dump(mode="json")
            self.fewshot.validate_report(review)
        return await self.infer({"examples_to_audit": self.fewshot.validation_examples()}, FewShotValidation,
                                validate=validate, system_prompt_override=system)

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
                   "private_scope_findings": [s.model_dump(mode="json") for s in previous.private_judicial_support
                                              if not s.judicial_relevance_confirmed or not s.conclusion_consistent],
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
        # Private adjudication flags are descriptive audit metadata. They do not
        # veto a facts-supported question that the court chose not to adjudicate.
        expected = {f.feedback_id for f in feedback}
        actual = [r.feedback_id for r in output.responses_to_feedback]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("Respond exactly once to every current feedback_id")
        for response in output.responses_to_feedback:
            if response.decision == "CONTEST" and not self.config.enable_generator_rebuttal:
                raise ValueError("Contesting disabled by configuration")
