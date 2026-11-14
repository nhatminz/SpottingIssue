"""Semantic decisions are mocked; tests verify routing, privacy and acceptance.

These fixtures do not claim that a live LLM always makes correct legal judgments.
"""
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from legal_issue_pipeline import schemas
from legal_issue_pipeline.config import PipelineConfig
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from legal_issue_pipeline.validators.format_validator import candidate_errors
from legal_issue_pipeline.validators.judge_validator import scope_rubric_passes
from conftest import FakeClient, gen_data, judge_data, critique, assessment
from test_fac_agents_and_debate import assert_judge_isolated


FACTS = 'Nguyễn Văn A lấy chiếc điện thoại của B đem bán lấy tiền tiêu xài.'
PARAPHRASE = 'A đã chiếm đoạt tài sản thuộc sở hữu của B để sử dụng tiền vào mục đích cá nhân.'
SHORT_FACTS = 'A lấy chiếc điện thoại của B.'
UNSUPPORTED = 'A dùng vũ lực đe dọa B trước khi lấy điện thoại.'


def judgment_record(record, facts=FACTS):
    value = deepcopy(record)
    value['benchmark_seed'].update(facts_clean=facts, facts=facts+' RAW_FACTS_ONLY_SENTINEL_748')
    return value


def candidate(explain=PARAPHRASE, *, sold=True, decision=None):
    value = gen_data()
    subject = 'của A đối với việc lấy điện thoại của B'
    circumstance = 'A đem bán điện thoại để lấy tiền tiêu xài' if sold else 'chiếc điện thoại thuộc sở hữu của B'
    value['issues'][0].update(
        issue_text=f'Trách nhiệm pháp lý {subject} khi {circumstance}',
        explain=explain, focus_group='LIABILITY', focus='Trách nhiệm pháp lý',
        subject_action=subject, decisive_fact=circumstance,
    )
    if decision:
        value['responses_to_feedback'] = [{
            'feedback_id': 'F1', 'decision': decision,
            'facts_argument': 'Việc lấy tài sản của người khác và bán lấy tiền cho bản thân cho phép diễn đạt bằng một nhận định pháp lý; cách viết khác không bổ sung sự kiện mới.',
        }]
    return value


def review(current, *, unsupported=False, assessment_decision=None):
    value = critique('UNSUPPORTED_FACT') if unsupported else judge_data()
    value['coverage_analysis'][0].update(issue_text=current['issues'][0]['issue_text'], explanation='Hành vi lấy điện thoại thuộc người khác làm phát sinh vấn đề trách nhiệm pháp lý.')
    value['per_issue_reviews'][0]['explanation'] = (
        'Chi tiết dùng vũ lực/đe dọa không được mô tả hay suy ra từ việc lấy điện thoại; giải thích thiếu căn cứ.'
        if unsupported else 'Diễn đạt về chiếm đoạt tài sản và mục đích sử dụng tiền được tình tiết lấy, bán điện thoại để tiêu xài hỗ trợ về ý nghĩa.'
    )
    if unsupported:
        value['generator_visible_feedback'][0].update(
            action='REVISE', problem='Issue I1: chi tiết A dùng vũ lực, đe dọa B không có căn cứ vì facts chỉ nêu việc lấy điện thoại. Loại bỏ chi tiết này và giải thích từ hành vi lấy tài sản đã được mô tả.'
        )
    if assessment_decision:
        value['rebuttal_assessments'] = [assessment(assessment_decision)]
    return value


def controller(config, gens, judges):
    return DebateController(GeneratorAgent(FakeClient(gens), config), JudgeAgent(FakeClient(judges), config), config)


async def test_A_valid_paraphrase_and_F_original_output_preservation(config, record):
    record = judgment_record(record)
    original = deepcopy(record)
    generated = candidate()
    assert PARAPHRASE not in FACTS
    assert not candidate_errors(schemas.GeneratorOutput.model_validate_json(json.dumps(generated)), FACTS, config)
    JSONLWriter(config.input_path).write([record])
    original_input = config.input_path.read_bytes()
    agents = []

    def make():
        c = controller(config, [generated], [review(generated)])
        agents.append(c)
        return c

    summary = await PipelineRunner(config, make).run()
    assert summary['accepted'] == 1 and summary['failed'] == summary['rejected'] == 0
    output = json.loads(config.output_path.read_text())
    assert set(output) == set(original) | {'issues', 'explain'}
    assert {k: output[k] for k in original} == original
    assert output['explain'] == [PARAPHRASE]
    assert config.input_path.read_bytes() == original_input and record == original
    case = agents[-1]
    assert len(case.generator.client.messages) == len(case.judge.client.messages) == 1
    assert_judge_isolated(case.judge.client.messages, record)
    assert summary['manifest']['export_policy'] == schemas.CONTRACT_VERSION


async def test_B_unsupported_violence_is_judged_then_corrected_through_debate(config, record):
    record = judgment_record(record, SHORT_FACTS)
    config.max_debate_rounds = 1
    bad = candidate(UNSUPPORTED, sold=False)
    fixed = candidate('Việc A lấy một tài sản thuộc về B đặt ra câu hỏi về trách nhiệm pháp lý của A đối với hành vi lấy điện thoại.', sold=False, decision='ACCEPT')
    c = controller(config, [bad, fixed], [review(bad, unsupported=True), review(fixed, assessment_decision='WITHDRAW')])
    result = await c.run(record)
    assert result.status.value == 'COMPLETED' and result.audit['rounds'] == 1
    first = result.audit['history'][0]['judge']
    assert first['per_issue_reviews'][0]['issue_supported'] is True
    assert first['per_issue_reviews'][0]['explain_supported'] is False
    feedback = first['generator_visible_feedback'][0]
    assert feedback['error_code'] == 'UNSUPPORTED_FACT' and 'vũ lực' in feedback['problem']
    assert 'vũ lực' not in result.explain[0]
    assert len(c.generator.client.messages) == 2  # revision, not structural JSON repair
    assert_judge_isolated(c.judge.client.messages, record)


@pytest.mark.parametrize('source', ['application', 'conclusion'])
async def test_C_private_only_fact_is_not_forwarded_as_source_and_is_not_accepted(config, record, source):
    record = judgment_record(record, SHORT_FACTS)
    record['benchmark_seed'][source] += ' '+UNSUPPORTED
    config.max_debate_rounds = 1
    bad = candidate(UNSUPPORTED, sold=False)
    unchanged = candidate(UNSUPPORTED, sold=False, decision='CONTEST')
    c = controller(config, [bad, unchanged], [review(bad, unsupported=True), review(unchanged, unsupported=True, assessment_decision='UPHOLD')])
    result = await c.run(record)
    assert result.status.value == 'REJECTED'
    assert result.audit['final_judge']['rubric']['grounding'] == 'FAIL'
    assert_judge_isolated(c.judge.client.messages, record)
    for messages in c.judge.client.messages:
        payload = json.loads(messages[1]['content'])
        assert payload['facts_clean'] == SHORT_FACTS
        assert payload['current_candidate']['issues'][0]['explain'] == UNSUPPORTED
        assert 'private_judicial_support' not in json.dumps(payload)


@pytest.mark.parametrize('decision', ['CONTEST', 'PARTIALLY_ACCEPT'])
async def test_D_valid_legal_paraphrase_can_contest_and_judge_withdraws(config, record, decision):
    record = judgment_record(record)
    first, rebuttal = candidate(), candidate(decision=decision)
    wrong = review(first, unsupported=True)
    wrong['generator_visible_feedback'][0]['problem'] = 'Thuật ngữ chiếm đoạt không có trong câu nguồn; yêu cầu làm rõ suy luận.'
    c = controller(config, [first, rebuttal], [wrong, review(rebuttal, assessment_decision='WITHDRAW')])
    result = await c.run(record)
    assert result.status.value == 'COMPLETED'
    sent = json.loads(c.judge.client.messages[-1][1]['content'])
    public_argument = sent['current_candidate']['responses_to_feedback'][0]['facts_argument']
    assert public_argument == rebuttal['responses_to_feedback'][0]['facts_argument'] and public_argument not in FACTS
    received = json.loads(c.generator.client.messages[-1][1]['content'])
    assert received['feedback'][0]['problem'] == wrong['generator_visible_feedback'][0]['problem']
    assert result.audit['judge_changes'] == 1
    assert_judge_isolated(c.judge.client.messages, record)


def test_E_all_structured_schemas_and_acceptance_have_no_exact_evidence_dependencies():
    for item in vars(schemas).values():
        if isinstance(item, type) and issubclass(item, schemas.Structured):
            schema = json.dumps(item.model_json_schema())
            assert 'evidence_quotes' not in schema and 'span_id' not in schema
    source = Path(__file__).resolve().parents[2] / 'src/legal_issue_pipeline'
    assert not (source / 'validators/evidence_validator.py').exists()
    for path in source.rglob('*.py'):
        text = path.read_text()
        assert 'validate_quotes(' not in text and 'non-verbatim facts_clean evidence' not in text
    assert 'enable_evidence_validation' not in PipelineConfig.model_fields


@pytest.mark.parametrize('flag', ['issue_supported', 'explain_supported'])
def test_adverse_pair_flag_cannot_be_exported_as_pass(flag):
    value = judge_data()
    value['per_issue_reviews'][0][flag] = False
    assert not scope_rubric_passes(value)


async def test_schema_failure_still_uses_three_attempts_then_fails(config, record):
    config.max_json_repair_retries = 2
    invalid = candidate()
    invalid['issues'][0]['issue_id'] = 'application private text'
    agent = GeneratorAgent(FakeClient([invalid, invalid, invalid]), config)
    with pytest.raises(LLMError, match='structured validation exhausted'):
        await agent.generate(record)
    assert len(agent.client.messages) == 3


async def test_private_non_adjudication_is_descriptive_without_judge_disclosure(config, record):
    config.max_debate_rounds = 1
    first = gen_data()
    first['private_judicial_support'][0]['judicial_relevance_confirmed'] = False
    c = controller(config, [first, gen_data()], [judge_data(), judge_data()])
    result = await c.run(record)
    assert result.status.value == 'COMPLETED' and result.audit['rounds'] == 0
    assert result.audit['final_generator']['private_judicial_support'][0]['judicial_relevance_confirmed'] is False
    assert_judge_isolated(c.judge.client.messages, record)


async def test_final_candidate_cannot_inherit_an_earlier_pass(config, record):
    record = judgment_record(record, SHORT_FACTS)
    config.enable_early_stop = False
    config.max_debate_rounds = 1
    first = candidate('Việc A lấy điện thoại thuộc sở hữu B đặt ra vấn đề xác định trách nhiệm pháp lý từ hành vi lấy tài sản.', sold=False)
    bad = candidate(UNSUPPORTED, sold=False)
    c = controller(config, [first, bad], [review(first), review(bad, unsupported=True)])
    result = await c.run(record)
    assert result.audit['history'][0]['judge']['overall_verdict'] == 'PASS'
    assert result.status.value == 'REJECTED'
    assert result.audit['final_judge']['per_issue_reviews'][0]['explain_supported'] is False


async def test_G_old_contract_checkpoint_is_refused_without_changing_old_files(config, record):
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config, lambda: controller(config, [gen_data()], [judge_data()])).run()
    path = config.checkpoint_dir / 'state.sqlite3'
    db = sqlite3.connect(path)
    manifest = json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
    manifest['export_policy'] = 'fac_semantic_grounding_v4'
    db.execute("UPDATE metadata SET value=? WHERE key='manifest'", (json.dumps(manifest),))
    db.commit(); db.close()
    files = [path, config.checkpoint_dir/'manifest.json', config.output_path, config.rejected_path]
    before = {p: p.read_bytes() for p in files}

    def never():
        pytest.fail('Incompatible checkpoint must not trigger inference')

    with pytest.raises(ValueError, match='fingerprint mismatch'):
        await PipelineRunner(config, never).run()
    assert {p: p.read_bytes() for p in files} == before
