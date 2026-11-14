from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path
import pytest
from legal_issue_pipeline.config import AgentConfig, PipelineConfig
from legal_issue_pipeline.llm.base_client import Completion
from legal_issue_pipeline.schemas import GeneratorOutput, JudgeOutput
from legal_issue_pipeline.validators.judge_validator import RUBRIC_CRITERIA

ROOT = Path(__file__).resolve().parents[1]
FACTS = 'Anh A yêu cầu ly hôn chị B. Chị B đã bị Tòa án tuyên bố mất tích.'
SITUATION = FACTS  # Historical name only for reusable API tests.
APPLICATION = 'Tòa xem xét yêu cầu ly hôn của anh A. APP_ONLY_SENTINEL_847.'
CONCLUSION = 'Chấp nhận yêu cầu ly hôn của anh A. CONCLUSION_ONLY_SENTINEL_219.'


def issue_data():
    return dict(issue_id='I1',issue_text='Việc xác định quyền yêu cầu ly hôn của anh A khi chị B đã bị Tòa án tuyên bố mất tích',
        explain='Anh A yêu cầu ly hôn, trong khi chị B đã bị tuyên bố mất tích. Các dữ kiện này đặt ra vấn đề xác định quyền yêu cầu chấm dứt quan hệ hôn nhân của anh A.',
        focus_group='DETERMINATION',focus='Việc xác định quyền',subject_action='yêu cầu ly hôn của anh A',
        decisive_fact='chị B đã bị Tòa án tuyên bố mất tích')


def gen_data():
    return dict(issues=[issue_data()],responses_to_feedback=[],private_judicial_support=[dict(issue_id='I1',
        judicial_relevance_confirmed=True,conclusion_consistent=True,explanation='Yêu cầu ly hôn được xem xét và giải quyết độc lập. PRIVATE_GENERATOR_AUDIT_991')])


def criterion(status='PASS', reason='Dữ kiện và câu hỏi pháp lý phù hợp.'):
    return dict(status=status, reason=reason)


def criterion_groups():
    return dict(
        factual_grounding={k:{**criterion(), 'basis':'FACT'} for k in
            ('actor_grounding','conduct_grounding','object_grounding','decisive_fact_grounding','semantic_inference')},
        subject_liability={k:criterion() for k in ('subject_precision','conduct_attribution','liability_precision','subject_grouping')},
        atomicity={k:criterion() for k in ('atomicity','independence','overlap','granularity')},
        explanation_review={k:criterion() for k in ('factual_basis','legal_connection','issue_alignment')})


def coverage_tests():
    return {k:criterion() for k in ('facts_grounding','legal_relevance','independence','existing_coverage')}


def judge_data(verdict='PASS', blind=False):
    return dict(per_issue_reviews=[dict(issue_id='I1',issue_supported=True,explain_supported=True,
        **criterion_groups(), classification='CORE',related_issue_ids=[],verdict='PASS',error_codes=[],
        explanation='Cặp issue/explain có đủ căn cứ từ facts_clean.')],
        rubric={**{key:'PASS' for key in RUBRIC_CRITERIA},'explanation':'Đã kiểm tra từng cặp và độ bao phủ từ facts.'},
        coverage_analysis=[dict(coverage_id='C1',issue_text=issue_data()['issue_text'],explanation='Yêu cầu chấm dứt hôn nhân và tình trạng mất tích làm phát sinh vấn đề quyền ly hôn.',matched_issue_ids=['I1'],tests=coverage_tests())],
        blind_comparison=[dict(discovery_issue_id='D1',disposition='MATCHED',coverage_issue_ids=['C1'],matched_issue_ids=['I1'],
            explanation='Đề xuất được facts hỗ trợ và candidate bao phủ.')] if blind else [],
        cross_issue_evaluation={**{k:criterion() for k in ('coverage','deduplication','fragmentation','over_merging')},'findings':[]},
        error_codes=[],feedback='Đã kiểm tra facts-only.',generator_visible_feedback=[],rebuttal_assessments=[],
        overall_verdict=verdict,unresolved_disputes=[])


def critique(code='INVALID_EXPLANATION'):
    value=judge_data('REVISE')
    value['per_issue_reviews'][0].update(verdict='REVISE',error_codes=[code], explain_supported=False)
    path = 'factual_basis' if code == 'UNSUPPORTED_FACT' else 'legal_connection'
    value['per_issue_reviews'][0]['explanation_review'][path] = criterion('FAIL', 'Giải thích chưa hỗ trợ câu hỏi được nêu.')
    value['rubric']['explanation_quality']='FAIL';value['rubric']['consistency']='FAIL';value['error_codes']=[code]
    value['generator_visible_feedback']=[dict(feedback_id='F1',issue_ids=['I1'],error_code=code,action='RECONSIDER',
        failed_criterion='explanation_review.'+path,
        problem='Giải thích chưa hỗ trợ câu hỏi pháp lý.',
        reason='Cần làm rõ quan hệ giữa tình tiết quyết định và yêu cầu ly hôn.',
        requested_change='Giải thích cụ thể vì sao facts làm phát sinh vấn đề này.')]
    if code == 'UNSUPPORTED_FACT':
        value['rubric']['grounding']='FAIL'
    return value


def response(decision='CONTEST'):
    value=gen_data()
    value['responses_to_feedback']=[dict(feedback_id='F1',decision=decision,
        facts_argument='Yêu cầu chấm dứt hôn nhân xuất phát từ A, còn người vợ đã được xác định mất tích; diễn đạt này được tình tiết hỗ trợ.')]
    value['private_judicial_support'][0]['explanation']+=' PRIVATE_REBUTTAL_NARRATIVE_005'
    return value


def assessment(decision='WITHDRAW'):
    return dict(feedback_id='F1',decision=decision,explanation='Đánh giá lại ý nghĩa và suy luận từ những tình tiết đã cho.')


def discovery_data():
    return {'issues':[{'issue_id':'D1','issue_text':issue_data()['issue_text'],'explanation':'Yêu cầu ly hôn cùng việc mất tích đặt ra câu hỏi quyền chấm dứt hôn nhân.'}]}


def fewshot_report(examples):
    return {'checks':[dict(example_id=example['example_id'],issue_index=index,issue_supported=True,explain_supported=True,
        explanation='Các dữ kiện hỗ trợ ý nghĩa của cặp issue/explain này.')
        for example in examples for index in range(len(example['issues']))]}


def fewshot_review(examples):
    return fewshot_report(examples)


class FakeClient:
    def __init__(self, values):
        self.values=list(values);self.messages=[];self.calls=[];self.closed=False
    async def complete(self,messages,schema):
        self.messages.append(deepcopy(messages))
        payload=json.loads(messages[1]['content'])
        if 'examples_to_audit' in payload:
            value=fewshot_review(payload['examples_to_audit'])
        else:
            value=self.values.pop(0)
        if isinstance(value,Exception):raise value
        self.calls.append({'role':'fake','request_id':str(len(self.messages)),'usage':{'total_tokens':10}})
        return Completion(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),{'total_tokens':10},0.001,str(len(self.messages)))
    async def close(self):self.closed=True


@pytest.fixture
def config(tmp_path):
    return PipelineConfig(project_root=ROOT,input_path=tmp_path/'input.jsonl',output_path=tmp_path/'output.jsonl',
        audit_dir=tmp_path/'audit',log_dir=tmp_path/'logs',checkpoint_dir=tmp_path/'checkpoints',prompt_dir=ROOT/'prompts',
        fewshot_path=ROOT/'input/fewshot.jsonl',gen=AgentConfig(),judge=AgentConfig(),
        max_json_repair_retries=0,retry_backoff=0,retry_jitter=0,enable_blind_judge_discovery=False,
        token_count_method='utf8_byte_upper_bound')


@pytest.fixture
def record():
    return dict(doc_name='case-1',benchmark_seed=dict(facts_clean=FACTS,facts=FACTS+' RAW_FACTS_ONLY_SENTINEL_748',
        application=APPLICATION,conclusion=CONCLUSION),markdown=FACTS+' '+APPLICATION+' '+CONCLUSION+' MARKDOWN_ONLY_SENTINEL_483',
        citations_law=[{'ref':'PRIVATE_CITATION'}],citations=[],category='Civil',other={'nested':[1,None,True]})


@pytest.fixture
def generator_output():return GeneratorOutput.model_validate_json(json.dumps(gen_data()))


@pytest.fixture
def judgment():return JudgeOutput.model_validate_json(json.dumps(judge_data()))
