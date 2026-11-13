"""Scope claims are semantic LLM judgments; these tests enforce their evidence contract."""
import json
from copy import deepcopy

import pytest

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.debate.state import EvaluatedCandidate
from legal_issue_pipeline.io.result_exporter import ResultExporter
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.schemas import GeneratorOutput,JudgeOutput
from legal_issue_pipeline.validators.format_validator import candidate_errors
from legal_issue_pipeline.validators.judge_validator import scope_rubric_passes
from conftest import FakeClient,SITUATION,COURT_QUOTE,gen_data,issue_data,judge_data,assessment


def parsed(data):
    return JudgeOutput.model_validate_json(json.dumps(data,ensure_ascii=False))


def extra_issue(text="Việc xác định tư cách người mất tích của chị B khi chị B đã bị Tòa án tuyên bố mất tích"):
    issue=issue_data()
    before,after=text.split(" khi ",1)
    prefix=next(p for p in ["Việc xác định tư cách","Việc xác định nghĩa vụ","Việc xác định quyền"] if before.startswith(p))
    issue.update(issue_id="I2",issue_text=text,focus=prefix,subject_action=before[len(prefix):].strip(),decisive_fact=after)
    return issue


def noncore_judgment(classification,code):
    data=judge_data("REVISE")
    review=deepcopy(data["per_issue_reviews"][0])
    review.update(issue_id="I2",classification=classification,court_scope_confirmed=False,
                  verdict="REMOVE",error_codes=[code],related_issue_ids=["I1"],
                  explanation="Đây không phải vấn đề pháp lý độc lập thuộc phạm vi Tòa giải quyết")
    data["per_issue_reviews"].append(review)
    data["error_codes"]=[code]
    data["rubric"]["legal_relevance"]="FAIL"
    data["generator_visible_feedback"]=[dict(feedback_id="F1",issue_ids=["I2","I1"],error_code=code,action="REMOVE",
        situation_evidence_quotes=[SITUATION],explanation="Tích hợp tình tiết đã có vào vấn đề trọng tâm, bỏ issue phụ")]
    return data


@pytest.mark.parametrize("classification,code,text",[
    ("SUPPORTING_FACT","SUPPORTING_FACT","Việc xác định tư cách người mất tích của chị B khi chị B đã bị Tòa án tuyên bố mất tích"),
    ("DUPLICATE","DUPLICATE","Việc xác định quyền ly hôn của anh A khi chị B đã bị Tòa án tuyên bố mất tích"),
    ("IRRELEVANT","ANCILLARY_ISSUE","Việc xác định nghĩa vụ chịu án phí của anh A khi anh A yêu cầu ly hôn chị B"),
    ("IRRELEVANT","ANCILLARY_ISSUE","Việc xác định quyền kháng cáo của anh A khi anh A yêu cầu ly hôn chị B"),
    ("IRRELEVANT","OUT_OF_SCOPE","Việc xác định nghĩa vụ của người liên quan C khi anh A yêu cầu ly hôn chị B"),
    ("IRRELEVANT","UNSUPPORTED_ISSUE","Việc xác định quyền yêu cầu bồi thường của anh A khi anh A yêu cầu ly hôn chị B"),
])
def test_well_formatted_noncore_issue_cannot_be_gold(config,record,classification,code,text):
    current=GeneratorOutput.model_validate_json(json.dumps({"issues":[issue_data(),extra_issue(text)],"responses_to_feedback":[]}))
    assert candidate_errors(current,record["situation"],config)==[]
    judgment=parsed(noncore_judgment(classification,code))
    judge=JudgeAgent(FakeClient([]),config)
    judge.validate_judgment(judgment,record,current,None)
    controller=DebateController(GeneratorAgent(FakeClient([]),config),judge,config)
    assert not controller._approved(EvaluatedCandidate(current,judgment,[],0))
    assert not scope_rubric_passes(judgment)
    judgment.overall_verdict="PASS"
    with pytest.raises(ValueError):
        judge.validate_judgment(judgment,record,current,None)


@pytest.mark.parametrize("criterion",["legal_relevance","coverage","grounding","format"])
def test_pass_requires_all_four_rubric_criteria(config,record,generator_output,criterion):
    data=judge_data();data["rubric"][criterion]="FAIL"
    with pytest.raises(ValueError,match="PASS requires"):
        JudgeAgent(FakeClient([]),config).validate_judgment(parsed(data),record,generator_output,None)


def missing_coverage():
    data=judge_data("REVISE")
    item=deepcopy(data["coverage_analysis"][0])
    item.update(coverage_id="C2",matched_issue_ids=[],issue_text="Việc xác định quyền nuôi con của anh A khi anh A yêu cầu trực tiếp nuôi con")
    data["coverage_analysis"].append(item)
    issue=issue_data();issue.update(issue_id="C2",issue_text=item["issue_text"],subject_action="nuôi con của anh A",decisive_fact="anh A yêu cầu trực tiếp nuôi con")
    data["suggested_missing_issues"]=[issue]
    data["rubric"]["coverage"]="FAIL"
    data["error_codes"]=["MISSING_CORE_ISSUE"]
    data["generator_visible_feedback"]=[dict(feedback_id="F1",issue_ids=[],error_code="MISSING_CORE_ISSUE",action="ADD",
        situation_evidence_quotes=[SITUATION],explanation="Thiếu vấn đề nuôi con được yêu cầu và xét xử")]
    return data


def test_coverage_gap_is_actionable_even_when_every_existing_issue_passes(config,record,generator_output):
    data=missing_coverage()
    record["situation"]+=" Anh A yêu cầu trực tiếp nuôi con."
    record["markdown"]+=" Giao con cho anh A trực tiếp nuôi dưỡng."
    data["coverage_analysis"][1]["situation_evidence_quotes"]=["Anh A yêu cầu trực tiếp nuôi con."]
    data["coverage_analysis"][1]["markdown_evidence_quotes"]=["Giao con cho anh A trực tiếp nuôi dưỡng."]
    data["suggested_missing_issues"][0]["situation_evidence_quotes"]=["Anh A yêu cầu trực tiếp nuôi con."]
    output=parsed(data)
    assert all(r.verdict=="PASS" for r in output.per_issue_reviews)
    JudgeAgent(FakeClient([]),config).validate_judgment(output,record,generator_output,None)
    assert not scope_rubric_passes(output)
    output.rubric.coverage="PASS"
    with pytest.raises(ValueError,match="Coverage cannot PASS"):
        JudgeAgent(FakeClient([]),config).validate_judgment(output,record,generator_output,None)


def test_inventory_must_cover_every_current_core_issue(config,record,generator_output):
    data=judge_data();data["coverage_analysis"]=[]
    with pytest.raises(ValueError,match="PASS requires"):
        JudgeAgent(FakeClient([]),config).validate_judgment(parsed(data),record,generator_output,None)


def test_missing_issue_cannot_be_added_from_markdown_only(config,record,generator_output):
    data=missing_coverage()
    data["suggested_missing_issues"][0]["situation_evidence_quotes"]=["PRIVATE_MARKDOWN_ONLY_FACT"]
    with pytest.raises(ValueError,match="quote absent"):
        JudgeAgent(FakeClient([]),config).validate_judgment(parsed(data),record,generator_output,None)


@pytest.mark.parametrize("where",["review","inventory"])
def test_scope_requires_actual_judgment_quotes(config,record,generator_output,where):
    data=judge_data()
    target=data["per_issue_reviews"][0] if where=="review" else data["coverage_analysis"][0]
    target["markdown_evidence_quotes"]=["Tòa không hề ghi câu này."]
    with pytest.raises(ValueError,match="quote absent"):
        JudgeAgent(FakeClient([]),config).validate_judgment(parsed(data),record,generator_output,None)


def test_exceptional_independent_fee_dispute_can_be_core(config,record,generator_output):
    situation_quote="Anh A yêu cầu được miễn án phí."
    court_quote="Tòa án chấp nhận yêu cầu miễn án phí của anh A."
    record["situation"]+=" "+situation_quote;record["markdown"]+=" "+court_quote
    issue=extra_issue("Việc xác định nghĩa vụ chịu án phí của anh A khi anh A yêu cầu được miễn án phí")
    issue["situation_evidence_quotes"]=[situation_quote]
    current=generator_output.model_copy(deep=True)
    current.issues.append(type(current.issues[0]).model_validate_json(json.dumps(issue)))
    data=judge_data()
    review=deepcopy(data["per_issue_reviews"][0]);review.update(issue_id="I2",situation_evidence_quotes=[situation_quote],markdown_evidence_quotes=[court_quote])
    data["per_issue_reviews"].append(review)
    data["coverage_analysis"].append(dict(coverage_id="C2",issue_text=issue["issue_text"],situation_evidence_quotes=[situation_quote],
        markdown_evidence_quotes=[court_quote],court_scope_confirmed=True,matched_issue_ids=["I2"]))
    output=parsed(data)
    JudgeAgent(FakeClient([]),config).validate_judgment(output,record,current,None)
    assert scope_rubric_passes(output)


async def test_supporting_fact_removed_through_debate_instead_of_silently_exported(config,record):
    config.max_debate_rounds=1
    initial=gen_data();initial["issues"].append(extra_issue())
    revised=gen_data();revised["responses_to_feedback"]=[dict(feedback_id="F1",decision="ACCEPT",
        explanation="Tình tiết mất tích đã nằm trong issue ly hôn; bỏ issue độc lập",situation_evidence_quotes=[SITUATION])]
    final=judge_data();final["rebuttal_assessments"]=[assessment("WITHDRAW")]
    controller=DebateController(GeneratorAgent(FakeClient([initial,revised]),config),
        JudgeAgent(FakeClient([noncore_judgment("SUPPORTING_FACT","SUPPORTING_FACT"),final]),config),config)
    result=await controller.run(record)
    assert result.status.value=="COMPLETED" and result.issues==[issue_data()["issue_text"]]
    assert result.audit["history"][0]["judge"]["per_issue_reviews"][1]["classification"]=="SUPPORTING_FACT"
    assert result.audit["scope_rubric"]["legal_relevance"]=="PASS"


def test_historical_format_only_pass_cannot_be_exported():
    old=judge_data()
    for key in ["rubric","coverage_analysis","blind_comparison"]:
        old.pop(key)
    assert not scope_rubric_passes(old)
    with pytest.raises(ValueError,match="validation proof"):
        ResultExporter.require_accepted(dict(status="COMPLETED",output={"issues":[issue_data()["issue_text"]]},
            audit=dict(consensus="PASS",required_validations_passed=True,final_issues=[issue_data()["issue_text"]],final_judge=old)))
