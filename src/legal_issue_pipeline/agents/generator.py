from __future__ import annotations
from ..schemas import GeneratorOutput, SafeFeedback, SafeAssessment
from ..validators.evidence_validator import validate_quotes
from ..validators.format_validator import candidate_errors
from .base_agent import BaseAgent


class GeneratorAgent(BaseAgent):
    def __init__(self, client, config):
        super().__init__(client, config, "generator_system.md")
        self.revision_prompt = (config.prompt_dir/"generator_revision.md").read_text(encoding="utf-8")

    async def generate(self, situation: str) -> GeneratorOutput:
        # Signature deliberately cannot receive a record or judgment fields.
        return await self.infer({"situation": situation}, GeneratorOutput,
                                validate=lambda output: self._validate_responses(output, [], situation))

    async def revise(self, situation: str, previous: GeneratorOutput, feedback: list[SafeFeedback],
                     assessments: list[SafeAssessment], own_history: list[dict]) -> GeneratorOutput:
        if any(type(f) is not SafeFeedback for f in feedback) or any(type(a) is not SafeAssessment for a in assessments):
            raise TypeError("Generator requires firewall-approved feedback/assessments")
        payload = {"situation": situation, "previous_issues": [i.model_dump(mode="json") for i in previous.issues],
                   "feedback": [f.model_dump(mode="json") for f in feedback],
                   "rebuttal_assessments": [a.model_dump(mode="json") for a in assessments],
                   "own_debate_history": own_history,
                   "allow_contest": self.config.enable_generator_rebuttal}
        return await self.infer(payload, GeneratorOutput, self.revision_prompt,
                                validate=lambda output: self._validate_responses(output, feedback, situation))

    def _validate_responses(self, output, feedback, situation):
        errors = candidate_errors(output,situation,self.config)
        if errors:
            raise ValueError("Generator candidate must be repaired: "+"; ".join(errors))
        expected = {f.feedback_id for f in feedback}
        actual = [r.feedback_id for r in output.responses_to_feedback]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("Respond exactly once to every current feedback_id")
        for response in output.responses_to_feedback:
            if response.decision == "CONTEST" and not self.config.enable_generator_rebuttal:
                raise ValueError("Contesting disabled by configuration")
            validate_quotes(response.situation_evidence_quotes, situation, "generator rebuttal", required=response.decision != "ACCEPT")
