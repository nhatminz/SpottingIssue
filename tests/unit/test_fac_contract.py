import json
from copy import deepcopy
import pytest
from pydantic import ValidationError
from legal_issue_pipeline.io.jsonl_reader import JSONLReader
from legal_issue_pipeline.io.fewshot import FewShotBank
from legal_issue_pipeline.schemas import FewShotValidation, JudgeOutput
from legal_issue_pipeline.validators.output_validator import make_output, validate_output
from legal_issue_pipeline.validators.format_validator import candidate_errors
from legal_issue_pipeline.validators.judge_validator import RUBRIC_CRITERIA, scope_rubric_passes
from conftest import ROOT, FACTS, issue_data, judge_data, fewshot_report


def test_actual_input_schema():
    rows=list(JSONLReader(ROOT/'input/sample_input.jsonl'))
    assert len(rows)==62 and all(r.data['benchmark_seed']['facts_clean'] for r in rows)
    assert not any('situation' in r.data for r in rows)


@pytest.mark.parametrize('field',['facts_clean','facts','application','conclusion'])
@pytest.mark.parametrize('bad',[None,'',[],{}])
def test_required_seed_fields_have_no_fallback(config,record,field,bad):
    record['benchmark_seed'][field]=bad
    config.input_path.write_text(json.dumps(record)+'\n')
    with pytest.raises(ValueError,match='benchmark_seed.'+field):list(JSONLReader(config.input_path))


@pytest.mark.parametrize('field',['issues','explain'])
def test_output_conflicts_are_explicit(config,record,field):
    record[field]=[];config.input_path.write_text(json.dumps(record)+'\n')
    with pytest.raises(ValueError,match='conflict'):list(JSONLReader(config.input_path))
    with pytest.raises(ValueError,match='conflict'):make_output(record,[],[])


def test_output_exact_preservation_and_alignment(record):
    original=deepcopy(record)
    output=make_output(record,['Câu hỏi pháp lý'],['Tình tiết cụ thể làm phát sinh vấn đề.'])
    assert record==original and set(output)==set(record)|{'issues','explain'}
    for key,value in record.items():assert output[key]==value
    output['other']['nested'][0]=123
    with pytest.raises(ValueError,match='Original field changed'):validate_output(record,output)
    with pytest.raises(ValueError,match='lengths'):make_output(record,['issue'],[])
    with pytest.raises(ValueError):make_output(record,['issue'],[''])


def test_existing_situation_error_is_preserved_as_input_metadata(record):
    record['situation_error']=None
    output=make_output(record,[],[])
    assert output['situation_error'] is None  # Never created or updated by this contract.


def test_fewshot_five_categories_mapping_and_projection(config,record):
    bank=FewShotBank(config.fewshot_path)
    examples,excluded=bank.for_record(record)
    assert len(examples)==5 and not excluded
    raw=[json.loads(line) for line in config.fewshot_path.read_text().splitlines()]
    for original,example in zip(raw,examples):
        assert example['issues']==[item['issue'] for item in original['issues']]
        assert example['explain']==[item['explain'] for item in original['issues']]
        assert example['facts_clean']==original['benchmark_seed']['facts_clean']
        assert set(example)=={'example_id','category','facts_clean','issues','explain'}
    bank.validate_report(FewShotValidation.model_validate_json(json.dumps(fewshot_report(examples))))


def test_fewshot_self_match_excluded_without_silent_answer_leak(config,record):
    bank=FewShotBank(config.fewshot_path)
    record['doc_name']='330709'
    examples,excluded=bank.for_record(record)
    assert len(examples)==4 and excluded==['E1']
    record['doc_name']='new-id';record['benchmark_seed']['facts_clean']=bank.examples[1]['facts_clean']
    assert bank.for_record(record)[1]==['E2']


def test_fewshot_unsupported_explain_blocks_reference_use(config):
    bank=FewShotBank(config.fewshot_path)
    data=fewshot_report(bank.examples);data['checks'][0]['explain_supported']=False
    with pytest.raises(ValueError,match='Unsupported few-shot'):
        bank.validate_report(FewShotValidation.model_validate_json(json.dumps(data)))
    data['checks']=[]
    with pytest.raises(ValueError,match='every issue/explain pair'):
        bank.validate_report(FewShotValidation.model_validate_json(json.dumps(data)))


@pytest.mark.parametrize('corruption',['missing','bad_quote','wrong_count'])
def test_invalid_fewshot_file_is_not_silently_used(config,tmp_path,corruption):
    rows=[json.loads(line) for line in config.fewshot_path.read_text().splitlines()]
    if corruption=='missing':rows[0]['benchmark_seed']['facts_clean']=''
    if corruption=='bad_quote':rows[0]['issues'][0]['explain']='Theo application, Tòa đã tuyên thắng kiện.'
    if corruption=='wrong_count':rows.pop()
    path=tmp_path/'bad.jsonl';path.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows))
    with pytest.raises(ValueError):FewShotBank(path)


@pytest.mark.parametrize('criterion',RUBRIC_CRITERIA)
def test_all_eight_criteria_required(criterion):
    data=judge_data();data['rubric'][criterion]='FAIL'
    assert not scope_rubric_passes(data)


def test_judge_schema_cannot_acquire_old_private_fields():
    data=judge_data();data['situation_audit']={}
    with pytest.raises(ValidationError):JudgeOutput.model_validate_json(json.dumps(data))
    data=judge_data();data['per_issue_reviews'][0]['markdown_evidence_quotes']=['secret']
    with pytest.raises(ValidationError):JudgeOutput.model_validate_json(json.dumps(data))


def test_format_and_explanation_grounding(config,generator_output):
    assert not candidate_errors(generator_output,FACTS,config)
    generator_output.issues[0].explanation_evidence_quotes=['NOT_IN_FACTS']
    assert any('UNSUPPORTED_FACT' in x for x in candidate_errors(generator_output,FACTS,config))
    generator_output.issues[0].explain='Tòa án nhận định và đã giải quyết yêu cầu này.'
    assert any('INVALID_EXPLANATION' in x for x in candidate_errors(generator_output,FACTS,config))


@pytest.mark.parametrize('line',['null','', '{"doc_name":"x","doc_name":"y"}', '{"doc_name":"x","bad":NaN}'])
def test_bad_json_and_duplicate_keys_are_rejected(config,line):
    config.input_path.write_text(line+'\n')
    with pytest.raises(ValueError):list(JSONLReader(config.input_path))


def test_full_generator_private_schema_is_absent_from_judge_schema():
    from legal_issue_pipeline.schemas import JudgeOutput, JudgeCandidate
    schema=json.dumps(JudgeOutput.model_json_schema())+json.dumps(JudgeCandidate.model_json_schema())
    assert all(key not in schema for key in ['application_evidence_quotes','conclusion_evidence_quotes','private_judicial_support','situation_audit'])


def test_shell_and_python_defaults_match_on_b200_paths(monkeypatch):
    from legal_issue_pipeline.config import load_config
    from legal_issue_pipeline.llm.adapters import adapter_for
    monkeypatch.delenv('PROJECT_ROOT',raising=False)
    value=load_config()
    assert str(value.project_root)=='/workspace/storage-shared/nlp/minhpn19/LegalDataset'
    assert value.input_path==value.project_root/'input/sample_input.jsonl'
    assert value.fewshot_path==value.project_root/'input/fewshot.jsonl'
    assert (value.max_workers,value.max_concurrent_requests,value.batch_size,value.max_debate_rounds)==(40,40,100,6)
    for agent in (value.gen,value.judge):
        assert agent.model=='DeepSeek-V4.1-Flash-1017' and agent.backend=='deepseek_vllm'
        assert agent.thinking_enabled and agent.thinking_effort=='high' and agent.max_output_tokens==131073
        assert adapter_for(agent).parameters(agent,value)[0]['chat_template_kwargs']=={'thinking':True,'reasoning_effort':50}
    with pytest.raises(ValidationError):
        type(value)(**{**value.model_dump(),'max_debate_rounds':7})


def test_safe_history_ids_cannot_be_a_private_text_channel():
    from legal_issue_pipeline.schemas import SafeFeedback
    with pytest.raises(ValidationError):
        SafeFeedback.model_validate_json(json.dumps(dict(feedback_id='F1',issue_ids=['APPLICATION_ONLY_SECRET'],
            error_code='UNSUPPORTED_FACT',action='REVISE',facts_evidence_quotes=[FACTS])))
