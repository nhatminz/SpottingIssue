from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.debate.state import EvaluatedCandidate
from conftest import FakeClient


def test_latest_approved_candidate_wins_over_older_long_quotes(config,generator_output,judgment):
    controller=DebateController(GeneratorAgent(FakeClient([]),config),JudgeAgent(FakeClient([]),config),config)
    older=EvaluatedCandidate(generator_output,judgment,[],0)
    latest_output=generator_output.model_copy(deep=True)
    latest_output.issues[0].situation_evidence_quotes=["Anh A yêu cầu ly hôn chị B."]
    latest=EvaluatedCandidate(latest_output,judgment,[],1)
    assert controller._select([older,latest]) is latest
