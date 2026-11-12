import asyncio
import json
import shutil
from copy import deepcopy

import httpx
import pytest

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from conftest import FakeClient,SITUATION,COURT_QUOTE,issue_data,gen_data,judge_data


def discovery_data():
    issue=issue_data();issue["issue_id"]="D1"
    return {"issues":[issue]}


async def test_blind_request_has_only_situation_and_no_prior_context(config,record):
    config.enable_blind_judge_discovery=True
    client=FakeClient([discovery_data(),judge_data(blind=True),discovery_data()])
    judge=JudgeAgent(client,config)
    judge.message_history.append([{"role":"user","content":"PRIOR_GENERATOR_SECRET"}])
    discovery=await judge.discover(record["situation"])
    current=await GeneratorAgent(FakeClient([gen_data()]),config).generate(record["situation"])
    await judge.evaluate(record,current,None,discovery,[],[])
    messages=client.messages[0]
    assert json.loads(messages[1]["content"])=={"situation":record["situation"]}
    assert len(messages)==2 and "BLIND ISSUE DISCOVERY" in messages[0]["content"]
    serialized=json.dumps(messages,ensure_ascii=False)
    for secret in ["PRIOR_GENERATOR_SECRET","PRIVATE_MARKDOWN_ONLY_FACT","PRIVATE_CITATION",COURT_QUOTE]:
        assert secret not in serialized
    with pytest.raises(TypeError,match="only the situation"):
        await judge.discover(record)
    second=json.loads(client.messages[1][1]["content"])
    assert second["blind_discovery"]==discovery_data()
    assert second["markdown"]==record["markdown"]
    await judge.discover(record["situation"])
    later=client.messages[2]
    assert len(later)==2 and json.loads(later[1]["content"])=={"situation":record["situation"]}
    assert COURT_QUOTE not in json.dumps(later,ensure_ascii=False)


async def test_evaluation_requires_stage_a_when_enabled(config,record,generator_output):
    config.enable_blind_judge_discovery=True
    judge=JudgeAgent(FakeClient([]),config)
    with pytest.raises(ValueError,match="requires the completed"):
        await judge.evaluate(record,generator_output,None,None,[],[])


async def test_controller_executes_blind_before_generator_then_evaluates(config,record):
    config.enable_blind_judge_discovery=True
    events=[]
    class OrderedClient(FakeClient):
        def __init__(self,role,values):super().__init__(values);self.role=role
        async def complete(self,messages,schema):
            events.append(self.role)
            return await super().complete(messages,schema)
    controller=DebateController(GeneratorAgent(OrderedClient("generator",[gen_data()]),config),
        JudgeAgent(OrderedClient("judge",[discovery_data(),judge_data(blind=True)]),config),config)
    result=await controller.run(record)
    assert events==["judge","generator","judge"]
    assert result.status.value=="COMPLETED"
    assert result.audit["blind_discovery"]==discovery_data()
    assert result.audit["blind_comparison"][0]["disposition"]=="MATCHED"
    assert result.audit["coverage_analysis"]


async def test_blind_proposal_can_be_excluded_with_evidence(config,record):
    config.enable_blind_judge_discovery=True
    blind=discovery_data()
    blind["issues"][0].update(issue_text="Việc xác định tư cách người mất tích của chị B khi chị B đã bị Tòa án tuyên bố mất tích",
        focus="Việc xác định tư cách",subject_action="người mất tích của chị B")
    data=judge_data(blind=True)
    data["blind_comparison"][0].update(disposition="EXCLUDED",coverage_issue_ids=[],matched_issue_ids=[],
        explanation="Tư cách mất tích là dữ kiện cho ly hôn, không phải yêu cầu độc lập đang được xét xử")
    controller=DebateController(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([blind,data]),config),config)
    result=await controller.run(record)
    assert result.status.value=="COMPLETED" and result.issues==[issue_data()["issue_text"]]
    assert result.audit["blind_comparison"][0]["disposition"]=="EXCLUDED"


async def test_stage_b_can_find_core_question_that_blind_discovery_missed(config,record):
    config.enable_blind_judge_discovery=True
    controller=DebateController(GeneratorAgent(FakeClient([gen_data()]),config),
        JudgeAgent(FakeClient([{"issues":[]},judge_data()]),config),config)
    result=await controller.run(record)
    assert result.status.value=="COMPLETED" and result.audit["coverage_analysis"]


async def test_missing_blind_core_issue_is_added_through_evidence_based_debate(config,record):
    config.enable_blind_judge_discovery=True
    source="Anh A yêu cầu trực tiếp nuôi con chung."
    court="Giao con chung cho anh A trực tiếp nuôi dưỡng."
    record["situation"]+=" "+source;record["markdown"]+=" "+court
    def custody(issue_id):
        item=issue_data()
        item.update(issue_id=issue_id,issue_text="Việc xác định quyền trực tiếp nuôi con chung của anh A khi anh A yêu cầu trực tiếp nuôi con chung",
            subject_action="trực tiếp nuôi con chung của anh A",decisive_fact="anh A yêu cầu trực tiếp nuôi con chung",
            situation_evidence_quotes=[source])
        return item
    blind=discovery_data();blind["issues"].append(custody("D2"))
    evaluation=judge_data("REVISE",blind=True)
    gap=dict(coverage_id="C2",issue_text=custody("C2")["issue_text"],court_scope_confirmed=True,
        situation_evidence_quotes=[source],markdown_evidence_quotes=[court],matched_issue_ids=[])
    evaluation["coverage_analysis"].append(gap)
    evaluation["suggested_missing_issues"]=[custody("C2")]
    evaluation["rubric"]["coverage"]="FAIL";evaluation["error_codes"]=["MISSING_CORE_ISSUE"]
    evaluation["generator_visible_feedback"]=[dict(feedback_id="F1",issue_ids=[],error_code="MISSING_CORE_ISSUE",action="ADD",
        situation_evidence_quotes=[source],explanation="Thiếu quyền nuôi con là yêu cầu độc lập được Tòa giải quyết")]
    comparison=dict(discovery_issue_id="D2",disposition="MISSING",coverage_issue_ids=["C2"],matched_issue_ids=[],
        situation_evidence_quotes=[source],markdown_evidence_quotes=[court],explanation="Đề xuất blind được xác nhận nhưng Generator chưa bao phủ")
    evaluation["blind_comparison"].append(comparison)
    revised=gen_data();revised["issues"].append(custody("I2"))
    revised["responses_to_feedback"]=[dict(feedback_id="F1",decision="ACCEPT",explanation="Bổ sung issue theo yêu cầu có trong tình huống",situation_evidence_quotes=[source])]
    final=judge_data(blind=True)
    review=deepcopy(final["per_issue_reviews"][0]);review.update(issue_id="I2",situation_evidence_quotes=[source],markdown_evidence_quotes=[court])
    final["per_issue_reviews"].append(review)
    final["coverage_analysis"].append({**gap,"matched_issue_ids":["I2"]})
    final["blind_comparison"].append({**comparison,"disposition":"MATCHED","matched_issue_ids":["I2"]})
    final["rebuttal_assessments"]=[dict(feedback_id="F1",decision="WITHDRAW",explanation="Bản sửa đã bao phủ yêu cầu nuôi con",situation_evidence_quotes=[source])]
    generator=GeneratorAgent(FakeClient([gen_data(),revised]),config)
    result=await DebateController(generator,JudgeAgent(FakeClient([blind,evaluation,final]),config),config).run(record)
    assert result.status.value=="COMPLETED" and len(result.issues)==2 and result.audit["rounds"]==1
    assert result.audit["history"][0]["judge"]["rubric"]["coverage"]=="FAIL"
    assert result.audit["blind_comparison"][1]["disposition"]=="MATCHED"
    assert court not in json.dumps(generator.client.messages,ensure_ascii=False)


@pytest.mark.parametrize("corruption",["missing_comparison","fake_id","unresolved"])
async def test_blind_comparison_cannot_be_ignored_or_passed_with_uncertainty(config,record,corruption):
    config.enable_blind_judge_discovery=True
    data=judge_data(blind=True)
    if corruption=="missing_comparison":data["blind_comparison"]=[]
    elif corruption=="fake_id":data["blind_comparison"][0]["discovery_issue_id"]="D999"
    else:data["blind_comparison"][0]["disposition"]="NEEDS_REVIEW"
    controller=DebateController(GeneratorAgent(FakeClient([gen_data()]),config),
        JudgeAgent(FakeClient([discovery_data(),data]),config),config)
    with pytest.raises(LLMError,match="structured validation exhausted"):
        await controller.run(record)


async def test_completed_blind_discovery_is_audited_even_when_generator_fails(config,record):
    config.enable_blind_judge_discovery=True
    JSONLWriter(config.input_path).write([record])
    def factory():
        return DebateController(GeneratorAgent(FakeClient([LLMError("generator unavailable")]),config),
            JudgeAgent(FakeClient([discovery_data()]),config),config)
    summary=await PipelineRunner(config,factory).run()
    assert summary["failed"]==1 and summary["rejected"]==0
    case=next(config.audit_dir.glob("0000*.json"))
    assert json.loads(case.read_text())["blind_discovery"]==discovery_data()


@pytest.mark.parametrize("filename",["benchmark_scope.md","judge_blind_discovery.md","generator_system.md",
                                     "judge_system.md","generator_revision.md","judge_reconsideration.md"])
async def test_new_scope_prompts_participate_in_resume_fingerprint(config,record,tmp_path,filename):
    config.enable_blind_judge_discovery=True
    directory=tmp_path/"prompts";shutil.copytree(config.prompt_dir,directory);config.prompt_dir=directory
    JSONLWriter(config.input_path).write([record])
    def factory():
        return DebateController(GeneratorAgent(FakeClient([gen_data()]),config),
            JudgeAgent(FakeClient([discovery_data(),judge_data(blind=True)]),config),config)
    await PipelineRunner(config,factory).run()
    p=directory/filename;p.write_text(p.read_text()+"\nUpdated rubric")
    with pytest.raises(ValueError,match="fingerprint mismatch"):
        await PipelineRunner(config,factory).run()


async def test_http_smoke_three_independent_requests_and_unchanged_output_schema(config,record):
    config.enable_blind_judge_discovery=True
    JSONLWriter(config.input_path).write([record])
    stages=[]
    def handler(request):
        body=json.loads(request.content)
        payload=json.loads(body["messages"][1]["content"])
        if "BLIND ISSUE DISCOVERY" in body["messages"][0]["content"]:
            assert payload=={"situation":record["situation"]}
            assert COURT_QUOTE not in json.dumps(body,ensure_ascii=False)
            stages.append("blind");answer=discovery_data()
        elif "current_candidate" in payload:
            assert payload["blind_discovery"]==discovery_data()
            assert payload["markdown"]==record["markdown"]
            stages.append("evaluate");answer=judge_data(blind=True)
        else:
            assert payload=={"situation":record["situation"]}
            stages.append("generate");answer=gen_data()
        assert body["max_tokens"]==131073
        assert body["chat_template_kwargs"]=={"thinking":True,"reasoning_effort":75}
        assert "reasoning_effort" not in body and "thinking" not in body
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(answer)},"finish_reason":"stop"}],
            "usage":{"total_tokens":40}})
    def factory():
        gate=asyncio.Semaphore(1)
        gen=OpenAICompatibleClient(config.gen,config,gate,"gen",httpx.MockTransport(handler))
        judge=OpenAICompatibleClient(config.judge,config,gate,"judge",httpx.MockTransport(handler))
        return DebateController(GeneratorAgent(gen,config),JudgeAgent(judge,config),config)
    summary=await PipelineRunner(config,factory).run()
    assert stages==["blind","generate","evaluate"] and summary["accepted"]==1
    result=json.loads(config.output_path.read_text())
    assert set(result)==set(record)|{"issues","situation_error"}
    for key in record:
        if key not in ["issues","situation_error"]:assert result[key]==record[key]
    assert summary["token_usage"]["total_tokens"]==120
    assert summary["effective_thinking"]["judge"]["actual_parameters"]["chat_template_kwargs"]["reasoning_effort"]==75
