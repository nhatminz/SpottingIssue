import json
from copy import deepcopy
import pytest
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent, public_candidate
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.schemas import JudgeOutput, SafeHistory
from conftest import (coverage_tests,FACTS,APPLICATION,CONCLUSION,FakeClient,gen_data,judge_data,critique,
                      response,assessment,discovery_data)


def controller(config, gens, judges):
    return DebateController(GeneratorAgent(FakeClient(gens),config),JudgeAgent(FakeClient(judges),config),config)


def assert_judge_isolated(messages,record):
    text=json.dumps(messages,ensure_ascii=False)
    for sentinel in ['APP_ONLY_SENTINEL_847','CONCLUSION_ONLY_SENTINEL_219','RAW_FACTS_ONLY_SENTINEL_748',
                     'MARKDOWN_ONLY_SENTINEL_483','PRIVATE_GENERATOR_AUDIT_991','PRIVATE_REBUTTAL_NARRATIVE_005','PRIVATE_CITATION']:
        assert sentinel not in text
    for call in messages:
        payload=json.loads(call[1]['content'])
        assert payload['facts_clean']==record['benchmark_seed']['facts_clean']
        assert not {'markdown','application','conclusion','facts','few_shot_examples','benchmark_seed'} & payload.keys()
        if 'current_candidate' in payload:
            for item in payload['current_candidate']['issues']:
                assert set(item)=={'issue_id','issue_text','explain'}


async def test_generator_reads_full_sources_and_five_examples(config,record):
    agent=GeneratorAgent(FakeClient([gen_data()]),config)
    output=await agent.generate(record)
    payload=json.loads(agent.client.messages[0][1]['content'])
    assert payload['benchmark_seed']==record['benchmark_seed'] and payload['markdown']==record['markdown']
    assert len(payload['few_shot_examples'])==5
    assert all(set(x)=={'example_id','category','facts_clean','issues','explain'} for x in payload['few_shot_examples'])
    assert output.issues[0].explain


async def test_leakage_firewall_includes_blind_retry_revision_and_final(config,record):
    config.enable_blind_judge_discovery=True;config.max_debate_rounds=1;config.max_json_repair_retries=1
    invalid=judge_data(blind=True);invalid['rubric']['extra_note']='invalid key to exercise Judge repair'
    adverse=critique();adverse['blind_comparison']=judge_data(blind=True)['blind_comparison']
    final=judge_data(blind=True);final['rebuttal_assessments']=[assessment()]
    c=controller(config,[gen_data(),response()],[discovery_data(),invalid,adverse,final])
    result=await c.run(record)
    assert result.status.value=='COMPLETED' and result.audit['rounds']==1
    assert len(c.judge.client.messages)==4
    assert_judge_isolated(c.judge.client.messages,record)
    assert c.generator.client is not c.judge.client
    revision=json.loads(c.generator.client.messages[-1][1]['content'])
    assert len(revision['few_shot_examples'])==5 and revision['benchmark_seed']==record['benchmark_seed']
    assert 'private_judicial_support' in revision['previous_candidate']
    assert result.audit['generator_contests']==1 and result.audit['judge_changes']==1


async def test_judge_refuses_full_record_and_unprojected_generator(config,record,generator_output):
    judge=JudgeAgent(FakeClient([]),config)
    with pytest.raises(TypeError):await judge.evaluate(record,generator_output,None,None,[])
    with pytest.raises(TypeError):await judge.discover(record)
    with pytest.raises(TypeError):await judge.evaluate(FACTS,public_candidate(generator_output,FACTS),None,None,[{'application':APPLICATION}])


@pytest.mark.parametrize('where',['issue','explain'])
async def test_unsupported_public_claim_is_a_semantic_judge_finding(config,record,where):
    config.max_debate_rounds=1
    record['benchmark_seed']['application']+=' Anh A đã đe dọa chị B bằng vũ lực.'
    value=gen_data()
    if where=='issue':
        value['issues'][0]['issue_text']+=' và anh A đã đe dọa chị B bằng vũ lực'
        value['issues'][0]['decisive_fact']+=' và anh A đã đe dọa chị B bằng vũ lực'
    else:value['issues'][0]['explain']+=' Anh A đã đe dọa chị B bằng vũ lực.'
    revised=deepcopy(value);revised['responses_to_feedback']=response()['responses_to_feedback']
    adverse=critique('UNSUPPORTED_FACT')
    adverse['per_issue_reviews'][0][where+'_supported']=False
    adverse['generator_visible_feedback'][0]['problem']='Không có tình tiết đe dọa bằng vũ lực trong facts_clean; loại bỏ chi tiết này khỏi cặp issue/explain.'
    final=deepcopy(adverse);final['rebuttal_assessments']=[assessment('UPHOLD')]
    c=controller(config,[value,revised],[adverse,final])
    result=await c.run(record)
    assert result.status.value=='REJECTED' and result.audit['rounds']==1
    assert result.audit['final_judge']['per_issue_reviews'][0]['error_codes']==['UNSUPPORTED_FACT']
    assert_judge_isolated(c.judge.client.messages,record)


async def test_unadjudicated_question_is_not_vetoed_by_private_scope(config,record):
    config.max_debate_rounds=1
    value=gen_data();value['private_judicial_support'][0]['conclusion_consistent']=False
    result=await controller(config,[value,deepcopy(value)],[judge_data(),judge_data()]).run(record)
    assert result.status.value=='COMPLETED' and result.audit['rounds']==0
    assert not result.audit['final_generator']['private_judicial_support'][0]['conclusion_consistent']


async def test_valid_issue_with_unsupported_explain_is_rejected_by_judge(config,record):
    config.max_debate_rounds=1
    value=gen_data();value['issues'][0]['explain']='Anh A có ba người con và đang tranh chấp toàn bộ tài sản chung với chị B.'
    revised=deepcopy(value);revised['responses_to_feedback']=response()['responses_to_feedback']
    final=critique();final['rebuttal_assessments']=[assessment('UPHOLD')]
    c=controller(config,[value,revised],[critique(),final])
    result=await c.run(record)
    assert result.status.value=='REJECTED' and not result.audit['scope_rubric']['explanation_quality']=='PASS'
    assert result.audit['final_judge']['per_issue_reviews'][0]['error_codes']==['INVALID_EXPLANATION']
    assert_judge_isolated(c.judge.client.messages,record)


@pytest.mark.parametrize('code',['MISSING_CORE_ISSUE','DUPLICATE','NON_ATOMIC','INVALID_FORMAT','PREMATURE_CONCLUSION','UNSUPPORTED_FACT','INCONSISTENT_EXPLANATION'])
async def test_actionable_findings_can_be_contested_and_withdrawn(config,record,code):
    final=judge_data();final['rebuttal_assessments']=[assessment()]
    c=controller(config,[gen_data(),response()],[critique(code),final])
    result=await c.run(record)
    assert result.status.value=='COMPLETED' and result.audit['rounds']==1
    assert result.audit['history'][0]['judge']['generator_visible_feedback'][0]['error_code']==code


@pytest.mark.parametrize('final_pass',[False,True])
async def test_exactly_six_revisions_seven_evaluations_no_seventh_revision(config,record,final_pass):
    config.stop_on_stagnation=False
    judges=[critique()]
    for index in range(6):
        value=judge_data() if final_pass and index==5 else critique()
        value['rebuttal_assessments']=[assessment('WITHDRAW' if final_pass and index==5 else 'UPHOLD')]
        judges.append(value)
    c=controller(config,[gen_data()]+[response() for _ in range(6)],judges)
    result=await c.run(record)
    assert result.audit['rounds']==6 and result.audit['judge_evaluations']==7
    assert len(c.generator.client.messages)==7 and len(c.judge.client.messages)==7
    assert result.status.value==('COMPLETED' if final_pass else 'REJECTED')
    assert_judge_isolated(c.judge.client.messages,record)


async def test_stagnation_tracks_explain_changes_and_rejects_unresolved(config,record):
    c=controller(config,[gen_data()]+[response() for _ in range(6)],
        [critique()]+[{**critique(),'rebuttal_assessments':[assessment('UPHOLD')]} for _ in range(6)])
    result=await c.run(record)
    assert result.status.value=='REJECTED' and result.audit['rounds']<6
    assert result.audit['stop_reason']=='STAGNATION'


async def test_early_pass_has_zero_revisions(config,record):
    c=controller(config,[gen_data()],[judge_data()])
    result=await c.run(record)
    assert result.status.value=='COMPLETED' and result.audit['rounds']==0 and result.audit['early_stop']


async def test_removing_bad_issue_does_not_break_previous_feedback_ids(config,record):
    value=gen_data();second=deepcopy(value['issues'][0]);second['issue_id']='I2';second['issue_text']=second['issue_text'].replace('yêu cầu ly hôn','đề nghị ly hôn');second['subject_action']='đề nghị ly hôn của anh A'
    value['issues'].append(second);support=deepcopy(value['private_judicial_support'][0]);support['issue_id']='I2';value['private_judicial_support'].append(support)
    review=judge_data('REVISE');adverse=deepcopy(review['per_issue_reviews'][0]);adverse.update(issue_id='I2',classification='DUPLICATE',related_issue_ids=['I1'],verdict='REMOVE',error_codes=['DUPLICATE'])
    review['per_issue_reviews'].append(adverse);review['rubric']['deduplication']='FAIL';review['error_codes']=['DUPLICATE']
    review['generator_visible_feedback']=[{**critique('DUPLICATE')['generator_visible_feedback'][0],'issue_ids':['I2'],'action':'REMOVE'}]
    final=judge_data();final['rebuttal_assessments']=[assessment()]
    c=controller(config,[value,response('ACCEPT')],[review,final])
    assert (await c.run(record)).status.value=='COMPLETED'


async def test_private_scope_notes_are_never_projected(config,record,generator_output):
    generator_output.private_judicial_support[0].explanation+=' '+APPLICATION+' '+CONCLUSION
    public=public_candidate(generator_output,FACTS).model_dump(mode='json')
    text=json.dumps(public)
    assert 'APP_ONLY_SENTINEL_847' not in text and 'CONCLUSION_ONLY_SENTINEL_219' not in text
    assert set(public)=={'issues','responses_to_feedback'}


async def test_private_metadata_cannot_be_added_to_filtered_history(config,generator_output):
    from pydantic import ValidationError
    history={'feedback':[],'responses':[],'assessments':[], 'private_judicial_support':APPLICATION}
    with pytest.raises(ValidationError):SafeHistory.model_validate_json(json.dumps(history))
    judge=JudgeAgent(FakeClient([]),config)
    with pytest.raises(TypeError):
        await judge.evaluate(FACTS,public_candidate(generator_output,FACTS),None,None,[history])
    assert judge.client.messages==[]


async def test_missing_core_inventory_cannot_pass(config,generator_output):
    value=judge_data();value['coverage_analysis'].append(dict(coverage_id='C2',issue_text='Việc xác định quyền trực tiếp nuôi con của anh A khi anh A yêu cầu nuôi con',
        explanation='Một câu hỏi trung tâm chưa được candidate đề cập.',matched_issue_ids=[],tests=coverage_tests()))
    from legal_issue_pipeline.validators.judge_validator import scope_rubric_passes, consistency_errors
    parsed=JudgeOutput.model_validate_json(json.dumps(value))
    JudgeAgent(FakeClient([]),config).validate_judgment(parsed,FACTS,public_candidate(generator_output,FACTS),None)
    assert not scope_rubric_passes(parsed) and consistency_errors(parsed)
