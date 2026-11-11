from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path
import pytest
from legal_issue_pipeline.config import AgentConfig, PipelineConfig
from legal_issue_pipeline.llm.base_client import Completion
from legal_issue_pipeline.schemas import GeneratorOutput, JudgeOutput

ROOT = Path(__file__).resolve().parents[1]
SITUATION = "Anh A yêu cầu ly hôn chị B. Chị B đã bị Tòa án tuyên bố mất tích."
COURT_QUOTE = "Tòa án chấp nhận yêu cầu ly hôn của anh A đối với chị B đã bị tuyên bố mất tích."


def issue_data():
    return dict(issue_id="I1",issue_text="Việc xác định quyền yêu cầu ly hôn của anh A khi chị B đã bị Tòa án tuyên bố mất tích",
                focus_group="DETERMINATION",focus="Việc xác định quyền",subject_action="yêu cầu ly hôn của anh A",
                decisive_fact="chị B đã bị Tòa án tuyên bố mất tích",situation_evidence_quotes=[SITUATION],importance="CORE")


def gen_data():
    return dict(issues=[issue_data()],responses_to_feedback=[])


def judge_data(verdict="PASS",blind=False):
    return dict(per_issue_reviews=[dict(issue_id="I1",classification="CORE",court_scope_confirmed=True,
        markdown_evidence_quotes=[COURT_QUOTE],related_issue_ids=[],verdict="PASS",error_codes=[],explanation="Có căn cứ",situation_evidence_quotes=[SITUATION])],
        rubric=dict(legal_relevance="PASS",coverage="PASS",grounding="PASS",format="PASS",explanation="Vấn đề có căn cứ và thuộc phạm vi giải quyết"),
        coverage_analysis=[dict(coverage_id="C1",issue_text=issue_data()["issue_text"],situation_evidence_quotes=[SITUATION],
            markdown_evidence_quotes=[COURT_QUOTE],court_scope_confirmed=True,matched_issue_ids=["I1"])],
        blind_comparison=[dict(discovery_issue_id="D1",disposition="MATCHED",coverage_issue_ids=["C1"],matched_issue_ids=["I1"],
            situation_evidence_quotes=[SITUATION],markdown_evidence_quotes=[COURT_QUOTE],explanation="Đối chiếu độc lập có căn cứ")] if blind else [],
        error_codes=[],feedback="Đã kiểm tra",suggested_missing_issues=[],generator_visible_feedback=[],rebuttal_assessments=[],
        situation_audit=dict(missing_facts=[],contradictions=[],needs_review=False,explanation="Không phát hiện thiếu dữ kiện trọng yếu"),
        overall_verdict=verdict,unresolved_disputes=[])


def critique(code="WRONG_LIABILITY"):
    data = judge_data("REVISE")
    data["per_issue_reviews"][0].update(verdict="REVISE",error_codes=[code])
    data["error_codes"] = [code]
    data["generator_visible_feedback"] = [dict(feedback_id="F1",issue_ids=["I1"],error_code=code,action="RECONSIDER",
        situation_evidence_quotes=[SITUATION],explanation="PRIVATE_MARKDOWN_ONLY_FACT: không được chuyển")]
    return data


def response(decision="CONTEST"):
    data = gen_data()
    data["responses_to_feedback"] = [dict(feedback_id="F1",decision=decision,explanation="Căn cứ trong tình huống đã đủ",situation_evidence_quotes=[SITUATION])]
    return data


def assessment(decision="WITHDRAW"):
    return dict(feedback_id="F1",decision=decision,explanation="Xét lại bằng chứng cụ thể từ Generator",situation_evidence_quotes=[SITUATION])


class FakeClient:
    def __init__(self, values):
        self.values = list(values)
        self.messages = []
        self.calls = []
        self.closed = False

    async def complete(self,messages,schema):
        self.messages.append(deepcopy(messages))
        value = self.values.pop(0)
        if isinstance(value,Exception):
            raise value
        self.calls.append({"role":"fake","request_id":str(len(self.messages))})
        return Completion(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),{"total_tokens":10},0.001,str(len(self.messages)))

    async def close(self):
        self.closed = True


@pytest.fixture
def config(tmp_path):
    return PipelineConfig(project_root=ROOT,input_path=tmp_path/"input.jsonl",output_path=tmp_path/"output.jsonl",
        audit_dir=tmp_path/"audit",log_dir=tmp_path/"logs",checkpoint_dir=tmp_path/"checkpoints",prompt_dir=ROOT/"prompts",
        gen=AgentConfig(),judge=AgentConfig(),max_json_repair_retries=0,retry_backoff=0,retry_jitter=0,
        enable_blind_judge_discovery=False)


@pytest.fixture
def record():
    return dict(doc_name="case-1",situation=SITUATION,markdown=SITUATION+"\n# Nhận định và quyết định\n"+COURT_QUOTE+" PRIVATE_MARKDOWN_ONLY_FACT",
                citations_law=[{"ref":"PRIVATE_CITATION_LAW"}],citations=[{"raw":"PRIVATE_CITATION"}],
                situation_error=None,other={"nested":[1,None,True]},category=None)


@pytest.fixture
def generator_output():
    return GeneratorOutput.model_validate_json(json.dumps(gen_data(),ensure_ascii=False))


@pytest.fixture
def judgment():
    return JudgeOutput.model_validate_json(json.dumps(judge_data(),ensure_ascii=False))
