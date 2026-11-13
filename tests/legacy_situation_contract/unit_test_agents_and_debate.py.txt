import json
import pytest
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import FeedbackFirewall, JudgeAgent, situation_error
from legal_issue_pipeline.agents.base_agent import parse_structured
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.schemas import JudgeOutput, GeneratorOutput
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.validators.format_validator import candidate_errors
from conftest import FakeClient, SITUATION, gen_data, judge_data, critique, response, assessment


def make_controller(config,gens,judges):
    return DebateController(GeneratorAgent(FakeClient(gens),config),JudgeAgent(FakeClient(judges),config),config)


async def test_generator_initial_input_only_situation(config,record):
    agent = GeneratorAgent(FakeClient([gen_data()]),config)
    await agent.generate(record["situation"])
    payload = json.loads(agent.client.messages[0][-1]["content"])
    assert payload == {"situation":record["situation"]}


async def test_two_way_contest_and_judge_withdraws(config,record):
    final = judge_data();final["rebuttal_assessments"]=[assessment()]
    controller = make_controller(config,[gen_data(),response()],[critique(),final])
    result = await controller.run(record)
    assert result.status.value == "COMPLETED"
    assert result.audit["generator_contests"] == result.audit["judge_changes"] == 1
    assert result.audit["rounds"] == 1
    assert len(controller.judge.client.messages) == 2
    assert controller.generator.message_history is not controller.judge.message_history
    for messages in controller.generator.client.messages:
        payload = json.loads(messages[1]["content"])
        serialized = json.dumps(payload)
        for forbidden in ["markdown","citations","citations_law","PRIVATE_MARKDOWN_ONLY_FACT","PRIVATE_CITATION"]:
            assert forbidden not in serialized


async def test_judge_receives_allowed_sources(config,record,generator_output):
    agent = JudgeAgent(FakeClient([judge_data()]),config)
    await agent.evaluate(record,generator_output,None,None,[],[])
    payload = json.loads(agent.client.messages[0][1]["content"])
    for key in ["situation","markdown","citations_law","citations"]:
        assert payload[key] == record[key]
    assert "other" not in payload


async def test_judge_can_uphold_and_final_evaluates_last_revision(config,record):
    config.max_debate_rounds=1
    held=critique();held["rebuttal_assessments"]=[assessment("UPHOLD")]
    controller=make_controller(config,[gen_data(),response()],[critique(),held])
    result=await controller.run(record)
    assert result.status.value == "REJECTED"
    assert result.audit["rounds"]==1 and result.audit["judge_evaluations"]==2
    last=json.loads(controller.judge.client.messages[-1][1]["content"])
    assert last["current_candidate"]["responses_to_feedback"][0]["decision"]=="CONTEST"
    assert last["previous_judgment"] is not None
    assert result.audit["history"][-1]["judge"]["rebuttal_assessments"][0]["explanation"]


async def test_early_stop(config,record):
    controller=make_controller(config,[gen_data()],[judge_data()])
    result=await controller.run(record)
    assert result.audit["early_stop"] and result.audit["rounds"]==0
    assert len(controller.generator.client.messages)==1


async def test_stagnation(config,record):
    config.max_stagnant_rounds=1
    held=critique();held["rebuttal_assessments"]=[assessment("UPHOLD")]
    controller=make_controller(config,[gen_data(),response(),response()],[critique(),held,held])
    result=await controller.run(record)
    assert result.audit["stop_reason"]=="STAGNATION"
    assert result.audit["stagnation_signals"]
    assert result.audit["rounds"]<config.max_debate_rounds


def test_private_prose_never_crosses_firewall(config,record,generator_output):
    data=JudgeOutput.model_validate_json(json.dumps(critique()))
    safe,_=FeedbackFirewall.project(data,record["situation"],generator_output)
    assert "PRIVATE_MARKDOWN_ONLY_FACT" not in json.dumps([s.model_dump(mode="json") for s in safe])
    data.generator_visible_feedback[0].situation_evidence_quotes=["PRIVATE_MARKDOWN_ONLY_FACT"]
    with pytest.raises(ValueError,match="absent"):
        FeedbackFirewall.project(data,record["situation"],generator_output)


def test_feedback_id_cannot_smuggle_private_data(record,generator_output):
    data=JudgeOutput.model_validate_json(json.dumps(critique()))
    data.generator_visible_feedback[0].feedback_id="PRIVATE_MARKDOWN_ONLY_FACT"
    with pytest.raises(ValueError,match="F plus digits"):
        FeedbackFirewall.project(data,record["situation"],generator_output)


def test_format_and_unsupported_evidence(config,generator_output):
    generator_output.issues[0].issue_text="Tòa án phải chấp nhận ly hôn"
    assert any("INVALID_FORMAT" in e for e in candidate_errors(generator_output,SITUATION,config))
    generator_output.issues[0].situation_evidence_quotes=["không có trong tình huống"]
    assert any("UNSUPPORTED_FACT" in e for e in candidate_errors(generator_output,SITUATION,config))


def test_material_missing_and_administrative_policy(judgment):
    from legal_issue_pipeline.schemas import FactFinding
    finding=FactFinding(fact="mất tích",markdown_evidence_quotes=["đã mất tích"],material=True,importance_reason="Ảnh hưởng quyền ly hôn",
        affected_issue="Quyền ly hôn",equivalent_in_situation=False,equivalence_assessment="Không có nội dung tương đương")
    judgment.situation_audit.missing_facts=[finding]
    assert situation_error(judgment,"material_missing") is True
    finding.material=False
    assert situation_error(judgment,"material_missing") is False
    finding.material=True;finding.equivalent_in_situation=True
    assert situation_error(judgment,"material_missing") is False
    judgment.situation_audit.missing_facts=[]
    judgment.situation_audit.contradictions=[finding]
    assert not situation_error(judgment,"material_missing")
    assert situation_error(judgment,"material_missing_or_contradiction")


async def test_audit_evidence_checked_and_uncertainty_needs_review(config,record):
    data=judge_data("NEEDS_REVIEW");data["situation_audit"]["needs_review"]=True
    controller=make_controller(config,[gen_data()],[data])
    result=await controller.run(record)
    assert result.status.value=="REJECTED"


async def test_json_repair_and_exhaustion(config):
    config.max_json_repair_retries=1
    client=FakeClient(["invalid JSON",gen_data()])
    result=await GeneratorAgent(client,config).generate(SITUATION)
    assert len(result.issues)==1 and len(client.messages)==2
    with pytest.raises(LLMError,match="structured validation exhausted"):
        await GeneratorAgent(FakeClient(["{}","{}"]),config).generate(SITUATION)


@pytest.mark.parametrize("text",['{broken','{"issues": [], "issues": [], "responses_to_feedback": []}', '{"issues":[],"responses_to_feedback":[],"extra":1}'])
def test_malformed_json_rejected(text):
    with pytest.raises(ValueError):
        parse_structured(text,GeneratorOutput)


async def test_cases_do_not_share_history(config,record):
    one=make_controller(config,[gen_data()],[judge_data()])
    two=make_controller(config,[gen_data()],[judge_data()])
    await one.run(record)
    assert two.generator.message_history==two.judge.message_history==[]


async def test_blind_discovery_separate_request(config,record):
    config.enable_blind_judge_discovery=True
    discovered=gen_data()["issues"];discovered[0]["issue_id"]="D1"
    controller=make_controller(config,[gen_data()],[{"issues":discovered},judge_data(blind=True)])
    await controller.run(record)
    assert len(controller.judge.client.messages)==2
    blind=json.loads(controller.judge.client.messages[0][1]["content"])
    assert "current_candidate" not in blind


async def test_inconsistent_pass_is_not_accepted(config,record):
    data=critique();data["overall_verdict"]="PASS"
    controller=make_controller(config,[gen_data()],[data])
    with pytest.raises(LLMError,match="PASS contradicts"):
        await controller.run(record)
