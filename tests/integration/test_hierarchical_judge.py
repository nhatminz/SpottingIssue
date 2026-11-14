"""Predetermined semantic judgments test protocol/routing, not live legal accuracy."""
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent, public_candidate
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.result_exporter import ResultExporter
from legal_issue_pipeline.schemas import GeneratorOutput, JudgeOutput, Feedback
from legal_issue_pipeline.validators.judge_validator import (
    ISSUE_CRITERIA, CRITERION_RUBRICS, consistency_errors, scope_rubric_passes,
)
from conftest import FakeClient, gen_data, judge_data, criterion, coverage_tests, response, assessment
from test_fac_agents_and_debate import assert_judge_isolated


def parsed(value):
    return JudgeOutput.model_validate_json(json.dumps(value, ensure_ascii=False))


def mark(value, path, status='FAIL', *, code='UNSUPPORTED_FACT', action='REVISE', reason='Chi tiết không được facts hỗ trợ.', issue_id='I1'):
    review = next(r for r in value['per_issue_reviews'] if r['issue_id'] == issue_id)
    group, key = path.split('.')
    review[group][key] = criterion(status, reason)
    if group == 'factual_grounding':
        review[group][key]['basis'] = 'UNSUPPORTED' if status == 'FAIL' else 'UNCERTAIN'
        review['issue_supported'] = False
    if group == 'explanation_review':
        review['explain_supported'] = False
    review.update(verdict='REVISE' if status == 'FAIL' else 'NEEDS_REVIEW', error_codes=[code])
    value['overall_verdict'] = 'REVISE' if status == 'FAIL' else 'NEEDS_REVIEW'
    for name in CRITERION_RUBRICS[path]:
        value['rubric'][name] = 'FAIL' if status == 'FAIL' else 'NEEDS_REVIEW'
    if code not in value['error_codes']:
        value['error_codes'].append(code)
    value['generator_visible_feedback'].append(dict(
        feedback_id=f"F{len(value['generator_visible_feedback'])+1}", issue_ids=[issue_id],
        failed_criterion=path, error_code=code, action=action, problem=reason,
        reason=reason, requested_change='Kiểm tra và chỉ giữ nội dung được facts hỗ trợ.'))
    return value


def case_candidate(text, explain, subject, circumstance):
    value = gen_data()
    value['issues'][0].update(issue_text=text, explain=explain, focus_group='LIABILITY',
        focus='Trách nhiệm pháp lý', subject_action=subject, decisive_fact=circumstance)
    return value


def case_record(record, facts):
    item = deepcopy(record)
    item['benchmark_seed']['facts_clean'] = facts
    return item


async def evaluate_once(config, record, current, value):
    client = FakeClient([value])
    agent = JudgeAgent(client, config)
    result = await agent.evaluate(record['benchmark_seed']['facts_clean'],
        public_candidate(GeneratorOutput.model_validate_json(json.dumps(current)), record['benchmark_seed']['facts_clean']),
        None, None, [])
    assert len(client.messages) == 1
    assert_judge_isolated(client.messages, record)
    return result


@pytest.mark.parametrize('path', ISSUE_CRITERIA)
@pytest.mark.parametrize('status', ['FAIL', 'UNCERTAIN'])
async def test_each_atomic_adverse_blocks_forged_pass_without_json_repair(config, record, path, status):
    config.max_json_repair_retries = 2
    value = mark(judge_data(), path, status)
    # Deliberately contradict the detailed review. Preserve the model's finding.
    value['overall_verdict'] = value['per_issue_reviews'][0]['verdict'] = 'PASS'
    value['per_issue_reviews'][0]['issue_supported'] = True
    value['per_issue_reviews'][0]['explain_supported'] = True
    result = await evaluate_once(config, record, gen_data(), value)
    assert not scope_rubric_passes(result)
    assert consistency_errors(result)
    assert getattr(getattr(result.per_issue_reviews[0], path.split('.')[0]), path.split('.')[1]).status == status


@pytest.mark.parametrize('field', ['failed_criterion', 'problem', 'reason', 'requested_change'])
def test_structured_feedback_requires_target_problem_reason_change(field):
    value = mark(judge_data(), 'explanation_review.issue_alignment')['generator_visible_feedback'][0]
    del value[field]
    with pytest.raises(ValidationError):
        Feedback.model_validate_json(json.dumps(value))


@pytest.mark.parametrize('group,key', [p.split('.') for p in ISSUE_CRITERIA])
def test_all_16_reviews_are_mandatory(group, key):
    value = judge_data()
    del value['per_issue_reviews'][0][group][key]
    with pytest.raises(ValidationError):
        parsed(value)
    assert not scope_rubric_passes(value)


def test_adverse_criterion_requires_explicit_feedback_reference():
    value = mark(judge_data(), 'subject_liability.conduct_attribution', code='WRONG_SUBJECT')
    value['generator_visible_feedback'][0]['failed_criterion'] = 'explanation_review.issue_alignment'
    assert any('no linked structured feedback' in e for e in consistency_errors(parsed(value)))
    value['generator_visible_feedback'][0]['criterion_refs'] = [
        {'issue_id':'I1', 'criterion':'subject_liability.conduct_attribution'}]
    assert consistency_errors(parsed(value)) == []


@pytest.mark.parametrize('claim, path, code', [
    ('A dùng vũ lực đe dọa B khi lấy điện thoại', 'factual_grounding.conduct_grounding', 'UNSUPPORTED_FACT'),
    ('B lấy điện thoại của A dù chỉ A lấy tài sản', 'subject_liability.conduct_attribution', 'WRONG_SUBJECT'),
])
async def test_invented_violence_and_wrong_actor_are_semantic_findings(config, record, claim, path, code):
    item = case_record(record, 'A lấy chiếc điện thoại của B.')
    current = case_candidate('Trách nhiệm pháp lý của A đối với điện thoại khi A lấy tài sản của B',
        claim + ', làm phát sinh câu hỏi pháp lý cần xác định.', 'của A đối với điện thoại', 'A lấy tài sản của B')
    value = mark(judge_data(), path, code=code, reason=claim+' không được facts xác nhận.')
    result = await evaluate_once(config, item, current, value)
    assert consistency_errors(result) == [] and not scope_rubric_passes(result)


async def test_true_facts_explaining_wrong_issue_fail_alignment(config, record):
    record['benchmark_seed']['facts_clean'] += ' A và B còn có hợp đồng vay tiền chưa thanh toán.'
    current = gen_data()
    current['issues'][0]['explain'] = 'A và B có quan hệ vay và chưa thanh toán, vì vậy cần xác định nghĩa vụ hoàn trả tiền vay.'
    value = mark(judge_data(), 'explanation_review.issue_alignment', code='INCONSISTENT_EXPLANATION',
        reason='Facts về khoản vay đúng nhưng không giải thích quyền ly hôn.')
    result = await evaluate_once(config, record, current, value)
    assert result.per_issue_reviews[0].issue_supported
    assert not result.per_issue_reviews[0].explain_supported
    assert not scope_rubric_passes(result) and consistency_errors(result) == []


@pytest.mark.parametrize('facts,subject,circumstance', [
    ('A và B cùng lấy điện thoại của C để bán.', 'của A và B về việc lấy điện thoại của C', 'hai người cùng lấy tài sản để bán'),
    ('A lấy điện thoại của B nhưng chưa xác định trách nhiệm cuối cùng.', 'của A về việc lấy điện thoại của B', 'chưa xác định trách nhiệm cuối cùng'),
    ('A làm hư xe của B rồi trả lại. B không yêu cầu bồi thường thêm.', 'của A đối với thiệt hại xe của B', 'xe đã trả lại và B không yêu cầu thêm'),
])
async def test_shared_question_unknown_outcome_and_no_extra_compensation_can_pass(config, record, facts, subject, circumstance):
    item = case_record(record, facts)
    current = case_candidate(f'Trách nhiệm pháp lý {subject} khi {circumstance}',
        facts+' Các dữ kiện đặt ra câu hỏi về trách nhiệm pháp lý từ hành vi đã mô tả.', subject, circumstance)
    # Descriptive court-scope flags are not an additional semantic veto.
    current['private_judicial_support'][0].update(judicial_relevance_confirmed=False, conclusion_consistent=False)
    value = judge_data()
    value['coverage_analysis'][0]['issue_text'] = current['issues'][0]['issue_text']
    c = DebateController(GeneratorAgent(FakeClient([current]),config),JudgeAgent(FakeClient([value]),config),config)
    result = await c.run(item)
    assert result.status.value == 'COMPLETED' and result.audit['rounds'] == 0
    assert_judge_isolated(c.judge.client.messages, item)
    from legal_issue_pipeline.validators.output_validator import make_output
    ResultExporter.require_accepted({'audit':result.audit, 'status':'COMPLETED',
        'output':make_output(item,result.issues,result.explain)})


async def test_genuine_attribution_uncertainty_remains_rejected_after_six_revisions(config, record):
    config.stop_on_stagnation = False
    config.max_json_repair_retries = 2
    item = case_record(record, 'A hoặc B đã lấy điện thoại của C; chưa rõ ai thực hiện.')
    current = case_candidate('Trách nhiệm pháp lý của B về việc lấy điện thoại khi người thực hiện chưa được xác định',
        'Chưa xác định A hay B đã lấy điện thoại của C, nên việc gán hành vi cho B cần được làm rõ.',
        'của B về việc lấy điện thoại', 'người thực hiện chưa được xác định')
    value = mark(judge_data(), 'subject_liability.conduct_attribution', 'UNCERTAIN',
        code='AMBIGUOUS_FACT', action='RECONSIDER', reason='Facts chưa xác định A hay B thực hiện hành vi.')
    revised = deepcopy(current)
    revised['responses_to_feedback'] = response()['responses_to_feedback']
    next_value = deepcopy(value)
    next_value['rebuttal_assessments'] = [assessment('UPHOLD')]
    c = DebateController(GeneratorAgent(FakeClient([current]+[revised]*6),config),
        JudgeAgent(FakeClient([value]+[next_value]*6),config),config)
    result = await c.run(item)
    assert result.status.value == 'REJECTED'
    assert result.audit['rounds'] == 6 and result.audit['judge_evaluations'] == 7
    assert len(c.generator.client.messages) == len(c.judge.client.messages) == 7
    assert result.audit['judge_consistency_errors'] == []
    assert result.audit['final_judge']['overall_verdict'] == 'NEEDS_REVIEW'
    assert_judge_isolated(c.judge.client.messages, item)


async def test_split_independent_actors_and_then_refresh_every_criterion(config, record):
    config.max_debate_rounds = 1
    current = gen_data()
    current['issues'][0].update(issue_text='Việc xác định nghĩa vụ của A và B khi A vay tiền và B bảo lãnh',
        explain='A vay tiền còn B bảo lãnh, đặt ra hai nghĩa vụ có căn cứ và điều kiện phát sinh khác nhau.',
        focus='Việc xác định nghĩa vụ', subject_action='của A và B', decisive_fact='A vay tiền và B bảo lãnh')
    item = case_record(record, 'A vay tiền chưa trả, B bảo lãnh cho A; có tranh chấp điều kiện thực hiện bảo lãnh.')
    value = mark(judge_data(), 'subject_liability.subject_grouping', code='OVER_MERGING', action='SPLIT',
        reason='Tách nghĩa vụ trả nợ của A và nghĩa vụ bảo lãnh của B vì điều kiện phát sinh độc lập.')
    value['cross_issue_evaluation']['over_merging'] = criterion('FAIL', 'Gộp hai nghĩa vụ độc lập.')
    value['cross_issue_evaluation']['findings'] = [dict(finding_id='X1',kind='OVER_MERGING',issue_ids=['I1'],explanation='Hai căn cứ nghĩa vụ khác nhau.')]
    value['generator_visible_feedback'][0].update(cross_issue_ids=['X1'], requested_change='Tách quyền/nghĩa vụ trả nợ của A và bảo lãnh của B, dựa trên hai quan hệ được facts mô tả.')
    fixed = deepcopy(current)
    fixed['issues'][0].update(issue_text='Việc xác định nghĩa vụ trả nợ của A khi A vay tiền chưa trả',
        focus='Việc xác định nghĩa vụ',subject_action='trả nợ của A',decisive_fact='A vay tiền chưa trả')
    second = deepcopy(fixed['issues'][0]);second.update(issue_id='I2',
        issue_text='Việc xác định nghĩa vụ bảo lãnh của B khi điều kiện bảo lãnh đang tranh chấp',
        subject_action='bảo lãnh của B',decisive_fact='điều kiện bảo lãnh đang tranh chấp')
    fixed['issues'].append(second)
    support = deepcopy(fixed['private_judicial_support'][0]);support['issue_id']='I2';fixed['private_judicial_support'].append(support)
    fixed['responses_to_feedback']=response('ACCEPT')['responses_to_feedback']
    final = judge_data()
    second_review=deepcopy(final['per_issue_reviews'][0]);second_review['issue_id']='I2';final['per_issue_reviews'].append(second_review)
    second_coverage=deepcopy(final['coverage_analysis'][0]);second_coverage.update(coverage_id='C2',matched_issue_ids=['I2']);final['coverage_analysis'].append(second_coverage)
    final['rebuttal_assessments']=[assessment()]
    c=DebateController(GeneratorAgent(FakeClient([current,fixed]),config),JudgeAgent(FakeClient([value,final]),config),config)
    result=await c.run(item)
    assert result.status.value=='COMPLETED' and len(result.issues)==2
    assert result.audit['history'][0]['judge_consistency_errors']==[]
    assert len(result.audit['final_judge']['per_issue_reviews'])==2
    for review in result.audit['final_judge']['per_issue_reviews']:
        for path in ISSUE_CRITERIA:
            group,key=path.split('.')
            assert review[group][key]['status']=='PASS'
    revision=json.loads(c.generator.client.messages[-1][1]['content'])
    assert revision['feedback'][0]['action']=='SPLIT' and 'bảo lãnh' in revision['feedback'][0]['requested_change']


async def test_omitted_interest_needs_independent_coverage_tests_and_add(config, record):
    item=case_record(record,'A vay B 100 triệu, lãi 1% mỗi tháng; A không trả gốc và lãi.')
    current=gen_data()
    current['issues'][0].update(issue_text='Việc xác định nghĩa vụ trả nợ gốc của A khi A chưa hoàn trả khoản vay',
        explain='A vay của B nhưng chưa hoàn trả gốc, đặt ra câu hỏi xác định nghĩa vụ trả tiền gốc theo quan hệ vay.',
        focus='Việc xác định nghĩa vụ',subject_action='trả nợ gốc của A',decisive_fact='A chưa hoàn trả khoản vay')
    value=judge_data('REVISE')
    value['coverage_analysis'][0]['issue_text']=current['issues'][0]['issue_text']
    value['coverage_analysis'].append(dict(coverage_id='C2',issue_text='Việc xác định nghĩa vụ trả lãi của A khi A chưa thanh toán lãi vay',
        explanation='Nghĩa vụ lãi theo thời gian độc lập với hoàn trả gốc.',matched_issue_ids=[],tests=coverage_tests()))
    value['rubric']['coverage']='FAIL';value['cross_issue_evaluation']['coverage']=criterion('FAIL','Thiếu nghĩa vụ lãi độc lập.')
    value['error_codes']=['MISSING_CORE_ISSUE']
    value['generator_visible_feedback']=[dict(feedback_id='F1',issue_ids=[],coverage_ids=['C2'],
        failed_criterion='COVERAGE',error_code='MISSING_CORE_ISSUE',action='ADD',problem='Thiếu câu hỏi trả lãi.',
        reason='Facts có lãi suất và chưa trả lãi, có thể xác định nghĩa vụ lãi riêng với gốc.',
        requested_change='Bổ sung nghĩa vụ trả lãi độc lập, không lặp lại nghĩa vụ trả gốc.')]
    result=await evaluate_once(config,item,current,value)
    assert consistency_errors(result)==[] and not scope_rubric_passes(result)
    value['coverage_analysis'][1]['tests']['independence']['status']='UNCERTAIN'
    assert any('ADD requires' in e for e in consistency_errors(parsed(value)))


async def test_blind_supporting_premise_excluded_without_add(config, record, generator_output):
    from legal_issue_pipeline.schemas import DiscoveryOutput
    config.enable_blind_judge_discovery=True
    discovery=DiscoveryOutput.model_validate_json(json.dumps({'issues':[dict(issue_id='D1',
        issue_text='Việc xác định tình trạng mất tích của chị B khi đã có quyết định tuyên bố mất tích',
        explanation='Tình tiết nền đã được xác lập.')]},ensure_ascii=False))
    value=judge_data()
    value['blind_comparison']=[dict(discovery_issue_id='D1',disposition='EXCLUDED',coverage_issue_ids=[],matched_issue_ids=[],
        explanation='Tình trạng mất tích là tiền đề cho quyền ly hôn, không phải câu hỏi độc lập trong facts này.')]
    judge=JudgeAgent(FakeClient([value]),config)
    result=await judge.evaluate(record['benchmark_seed']['facts_clean'],public_candidate(generator_output,record['benchmark_seed']['facts_clean']),None,discovery,[])
    assert scope_rubric_passes(result) and result.generator_visible_feedback==[]


async def test_semantic_duplicate_principal_obligations_are_targeted(config, record):
    item=case_record(record,'A vay của B 100 triệu và chưa hoàn trả tiền gốc.')
    current=gen_data()
    current['issues'][0].update(issue_text='Việc xác định nghĩa vụ trả nợ gốc của A khi A chưa hoàn trả khoản vay',
        explain='Khoản tiền vay của B chưa được A hoàn trả, đặt ra nghĩa vụ thanh toán gốc từ hợp đồng vay.',
        focus='Việc xác định nghĩa vụ',subject_action='trả nợ gốc của A',decisive_fact='A chưa hoàn trả khoản vay')
    second=deepcopy(current['issues'][0]);second.update(issue_id='I2',
        issue_text='Việc xác định nghĩa vụ hoàn trả tiền vay của A khi tiền gốc vẫn chưa được thanh toán',
        subject_action='hoàn trả tiền vay của A',decisive_fact='tiền gốc vẫn chưa được thanh toán')
    current['issues'].append(second)
    support=deepcopy(current['private_judicial_support'][0]);support['issue_id']='I2';current['private_judicial_support'].append(support)
    value=judge_data();second_review=deepcopy(value['per_issue_reviews'][0]);second_review['issue_id']='I2';value['per_issue_reviews'].append(second_review)
    value=mark(value,'atomicity.overlap',code='DUPLICATE',action='REMOVE',issue_id='I2',
        reason='I2 lặp lại đúng nghĩa vụ trả nợ gốc đã được I1 bao quát.')
    value['per_issue_reviews'][1].update(classification='DUPLICATE',related_issue_ids=['I1'],verdict='REMOVE')
    value['cross_issue_evaluation']['deduplication']=criterion('FAIL','I1 và I2 cùng nghĩa vụ gốc.')
    value['cross_issue_evaluation']['findings']=[dict(finding_id='X1',kind='DUPLICATE',issue_ids=['I1','I2'],explanation='Một nghĩa vụ gốc bị lặp.')]
    value['generator_visible_feedback'][0].update(cross_issue_ids=['X1'],requested_change='Giữ nghĩa vụ gốc tại I1, loại diễn đạt trùng I2.')
    value['coverage_analysis'][0]['issue_text']=current['issues'][0]['issue_text']
    result=await evaluate_once(config,item,current,value)
    assert consistency_errors(result)==[] and not scope_rubric_passes(result)


async def test_forged_pass_without_feedback_is_rejected_not_failed_or_repaired(config, record):
    value=mark(judge_data(),'explanation_review.factual_basis','UNCERTAIN',code='AMBIGUOUS_FACT')
    value['overall_verdict']='PASS';value['generator_visible_feedback']=[]
    config.max_json_repair_retries=2
    c=DebateController(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([value]),config),config)
    result=await c.run(record)
    assert result.status.value=='REJECTED' and result.audit['stop_reason']=='JUDGE_INCONSISTENT'
    assert len(c.judge.client.messages)==1 and result.audit['judge_consistency_errors']


@pytest.mark.parametrize('cross', ['coverage','deduplication','fragmentation','over_merging'])
def test_each_cross_issue_adverse_cannot_pass(cross):
    value=judge_data();value['cross_issue_evaluation'][cross]=criterion('UNCERTAIN','Chưa rõ kiểm tra toàn danh sách.')
    assert not scope_rubric_passes(value)


def test_exporter_rechecks_atomic_status_even_if_checkpoint_claims_completed(record):
    from legal_issue_pipeline.schemas import CONTRACT_VERSION
    from legal_issue_pipeline.validators.output_validator import make_output
    generated=gen_data()
    output=make_output(record,[generated['issues'][0]['issue_text']],[generated['issues'][0]['explain']])
    audit=dict(contract=CONTRACT_VERSION,consensus='PASS',required_validations_passed=True,
        final_judge=judge_data(),final_generator=generated,final_issues=output['issues'],final_explain=output['explain'])
    row=dict(status='COMPLETED',output=output,audit=audit)
    ResultExporter.require_accepted(row)
    audit['final_judge']['per_issue_reviews'][0]['atomicity']['atomicity']['status']='UNCERTAIN'
    with pytest.raises(ValueError,match='PASS'):
        ResultExporter.require_accepted(row)


async def test_accurate_paraphrase_uses_supported_inference_without_quote_matching(config, record):
    item=case_record(record,'A lấy điện thoại của B rồi bán lấy tiền tiêu xài.')
    current=case_candidate('Trách nhiệm pháp lý của A đối với tài sản của B khi A chiếm đoạt tài sản để tiêu xài',
        'Việc lấy và bán điện thoại của B lấy tiền tiêu xài làm phát sinh câu hỏi trách nhiệm pháp lý đối với hành vi chiếm đoạt tài sản.',
        'của A đối với tài sản của B','A chiếm đoạt tài sản để tiêu xài')
    value=judge_data()
    value['coverage_analysis'][0]['issue_text']=current['issues'][0]['issue_text']
    value['per_issue_reviews'][0]['factual_grounding']['semantic_inference'].update(
        basis='SUPPORTED_INFERENCE',reason='Lấy và bán tài sản của B để tiêu xài hỗ trợ cách diễn đạt chiếm đoạt về ý nghĩa.')
    result=await evaluate_once(config,item,current,value)
    assert scope_rubric_passes(result)
    assert 'chiếm đoạt' not in item['benchmark_seed']['facts_clean']


@pytest.mark.parametrize('facts,subject,circumstance', [
    ('A và B ly hôn, có con nhỏ; hai bên không yêu cầu cấp dưỡng.', 'của cha mẹ về cấp dưỡng cho con nhỏ', 'hai bên không yêu cầu cấp dưỡng'),
    ('A và B ly hôn, có nhà chung nhưng không yêu cầu Tòa chia nhà.', 'của A và B đối với nhà chung', 'hai bên không yêu cầu Tòa chia nhà'),
    ('A và B ly hôn, có nợ chung nhưng không yêu cầu Tòa phân định nghĩa vụ.', 'của A và B đối với nợ chung', 'hai bên không yêu cầu Tòa phân định nghĩa vụ'),
])
async def test_family_questions_are_not_vetoed_by_non_adjudication(config, record, facts, subject, circumstance):
    item=case_record(record,facts)
    current=gen_data()
    current['issues'][0].update(issue_text=f'Việc xác định quyền và nghĩa vụ {subject} khi {circumstance}',
        explain=facts+' Việc không yêu cầu giải quyết vẫn đặt ra câu hỏi về quyền và nghĩa vụ trong quan hệ được mô tả.',
        focus='Việc xác định quyền và nghĩa vụ',subject_action=subject,decisive_fact=circumstance)
    current['private_judicial_support'][0].update(judicial_relevance_confirmed=False,conclusion_consistent=False)
    c=DebateController(GeneratorAgent(FakeClient([current]),config),JudgeAgent(FakeClient([judge_data()]),config),config)
    assert (await c.run(item)).status.value=='COMPLETED'
    assert_judge_isolated(c.judge.client.messages,item)


async def test_schema_repair_still_works_for_missing_structured_feedback_field(config, record):
    config.max_json_repair_retries=1
    good=mark(judge_data(),'explanation_review.issue_alignment',code='INCONSISTENT_EXPLANATION')
    malformed=deepcopy(good);del malformed['generator_visible_feedback'][0]['requested_change']
    agent=JudgeAgent(FakeClient([malformed,good]),config)
    current=GeneratorOutput.model_validate_json(json.dumps(gen_data()))
    result=await agent.evaluate(record['benchmark_seed']['facts_clean'],public_candidate(current,record['benchmark_seed']['facts_clean']),None,None,[])
    assert len(agent.client.messages)==2 and result.overall_verdict=='REVISE'
    assert_judge_isolated(agent.client.messages,record)


def test_supported_flag_cannot_override_unsupported_basis():
    value=judge_data()
    value['per_issue_reviews'][0]['factual_grounding']['semantic_inference']['basis']='UNSUPPORTED'
    assert not scope_rubric_passes(value)


async def test_runner_persists_semantic_uncertainty_as_rejected_and_resume_skips_it(config, record):
    from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
    from legal_issue_pipeline.pipeline.runner import PipelineRunner
    value=mark(judge_data(),'subject_liability.conduct_attribution','UNCERTAIN',code='AMBIGUOUS_FACT')
    value['overall_verdict']='PASS';value['generator_visible_feedback']=[]
    JSONLWriter(config.input_path).write([record])
    def factory():
        return DebateController(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([value]),config),config)
    summary=await PipelineRunner(config,factory).run()
    assert summary['rejected']==1 and summary['accepted']==summary['failed']==0
    assert config.output_path.read_text()==''
    rejection=json.loads(config.rejected_path.read_text())
    assert rejection['status']=='REJECTED' and rejection['rejection_reasons']
    raw_review=rejection['feedback_history'][0]['judge']['per_issue_reviews'][0]
    assert raw_review['subject_liability']['conduct_attribution']['status']=='UNCERTAIN'
    def never():
        raise AssertionError('REJECTED case or cached approved few-shot must not run again')
    resumed=await PipelineRunner(config,never).run()
    assert resumed['rejected']==1 and resumed['failed']==0


@pytest.mark.parametrize('kind,path,code', [
    ('DUPLICATE','atomicity.overlap','DUPLICATE'),
    ('FRAGMENTATION','atomicity.granularity','FRAGMENTATION'),
    ('OVER_MERGING','atomicity.atomicity','OVER_MERGING'),
])
def test_cross_issue_findings_need_linked_feedback(kind,path,code):
    from legal_issue_pipeline.validators.judge_validator import CROSS_KINDS
    value=mark(judge_data(),path,code=code)
    ids=['I1']
    if kind != 'OVER_MERGING':
        second=deepcopy(judge_data()['per_issue_reviews'][0]);second['issue_id']='I2'
        value['per_issue_reviews'].append(second)
        coverage=deepcopy(value['coverage_analysis'][0]);coverage.update(coverage_id='C2',matched_issue_ids=['I2'])
        value['coverage_analysis'].append(coverage)
        ids.append('I2')
    value['cross_issue_evaluation'][CROSS_KINDS[kind]]=criterion('FAIL','Phân rã danh sách chưa phù hợp.')
    value['cross_issue_evaluation']['findings']=[dict(finding_id='X1',kind=kind,issue_ids=ids,explanation='Cần chỉnh câu hỏi độc lập được nêu.')]
    assert any('no linked cross-issue feedback' in e for e in consistency_errors(parsed(value)))
    value['generator_visible_feedback'][0]['cross_issue_ids']=['X1']
    assert consistency_errors(parsed(value))==[]
    assert not scope_rubric_passes(value)
