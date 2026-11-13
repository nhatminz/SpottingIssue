import asyncio
import json
import shutil
from copy import deepcopy
import pytest
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.pipeline.runner import PipelineRunner, create_manifest
from legal_issue_pipeline.llm.base_client import LLMError
from conftest import FakeClient,gen_data,judge_data,critique,response,assessment


def factory(config,fail=False,reject=False):
    def make():
        if reject:
            final=critique();final['rebuttal_assessments']=[assessment('UPHOLD')]
            gens=[gen_data(),response()];judges=[critique(),final]
        else:gens=[LLMError('server unavailable')] if fail else [gen_data()];judges=[judge_data()]
        return DebateController(GeneratorAgent(FakeClient(gens),config),JudgeAgent(FakeClient(judges),config),config)
    return make


async def test_pass_only_preserve_fields_order_and_resume(config,record):
    JSONLWriter(config.input_path).write([{**record,'doc_name':str(i)} for i in range(4)])
    result=await PipelineRunner(config,factory(config)).run()
    assert result['accepted']==4 and result['run_complete']
    rows=[json.loads(x) for x in config.output_path.read_text().splitlines()]
    assert [x['doc_name'] for x in rows]==list(map(str,range(4)))
    assert all(set(x)==set(record)|{'issues','explain'} and len(x['issues'])==len(x['explain']) for x in rows)
    def never():raise AssertionError('Cached cases or approved few-shot recomputed')
    resumed=await PipelineRunner(config,never).run()
    assert resumed['accepted']==4
    assert (config.audit_dir/'fewshot_validation.json').exists()


async def test_rejected_and_failed_not_in_main_and_failures_retry(config,record):
    config.max_debate_rounds=1;config.fail_on_record_error=False;config.max_workers=1
    JSONLWriter(config.input_path).write([{**record,'doc_name':str(i)} for i in range(3)])
    calls=0
    def make():
        nonlocal calls
        calls+=1
        # First factory call is the once-per-run few-shot audit.
        return factory(config,fail=calls==3,reject=calls==4)()
    summary=await PipelineRunner(config,make).run()
    assert (summary['accepted'],summary['failed'],summary['rejected'],summary['pending'])==(1,1,1,0)
    assert len(config.output_path.read_text().splitlines())==1
    rejection=json.loads(config.rejected_path.read_text())
    assert rejection['feedback_history'] and rejection['rejection_reasons'] and rejection['rounds']==1
    assert rejection['explain'] and 'situation_error' not in rejection
    resumed=await PipelineRunner(config,factory(config)).run()
    assert (resumed['accepted'],resumed['rejected'],resumed['failed'])==(2,1,0)
    assert [json.loads(x)['doc_name'] for x in config.output_path.read_text().splitlines()]==['0','1']


async def test_fail_fast_leaves_pending_and_keeps_no_fake_labels(config,record):
    config.max_workers=1
    JSONLWriter(config.input_path).write([{**record,'doc_name':str(i)} for i in range(3)])
    summary=await PipelineRunner(config,factory(config,fail=True)).run()
    assert summary['failed']==1 and summary['pending']==2 and summary['accepted']==0
    assert config.output_path.read_text()=='' and config.rejected_path.read_text()==''


@pytest.mark.parametrize('change',['input','fewshot','prompt','model','effort','old_export_policy'])
async def test_manifest_invalidates_old_inputs_examples_prompts_schema_config(config,record,tmp_path,change):
    copied=tmp_path/'prompts';shutil.copytree(config.prompt_dir,copied);config.prompt_dir=copied
    fewshot=tmp_path/'fewshot.jsonl';shutil.copy(config.fewshot_path,fewshot);config.fewshot_path=fewshot
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,factory(config)).run()
    if change=='input':JSONLWriter(config.input_path).write([{**record,'other':123}])
    if change=='fewshot':
        rows=[json.loads(x) for x in fewshot.read_text().splitlines()]
        rows[0]['issues'][0]['explain']+=' '
        fewshot.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows)+'\n')
    if change=='prompt':
        p=copied/'judge_system.md';p.write_text(p.read_text()+'\nNew facts-only rubric.')
    if change=='model':config.gen.model='different-model'
    if change=='effort':config.gen.thinking_effort='xhigh'
    if change=='old_export_policy':
        import sqlite3
        db=sqlite3.connect(config.checkpoint_dir/'state.sqlite3')
        value=json.loads(db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0]);value['export_policy']='pass_only_v2'
        db.execute("UPDATE metadata SET value=? WHERE key='manifest'",(json.dumps(value),));db.commit();db.close()
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        await PipelineRunner(config,factory(config)).run()


async def test_dry_run_validates_files_without_inference_or_output(config,record):
    JSONLWriter(config.input_path).write([record]);config.dry_run=True
    def never():raise AssertionError('dry-run called LLM')
    result=await PipelineRunner(config,never).run()
    assert result['dry_run'] and result['fewshot_examples']==5
    assert not config.output_path.exists() and not config.checkpoint_dir.exists()


async def test_actual_sample_dry_run_reports_five_overlaps(config):
    config.input_path=config.project_root/'input/sample_input.jsonl';config.dry_run=True
    result=await PipelineRunner(config).run()
    assert result['selected_records']==62 and len(result['fewshot_overlaps'])==5


async def test_40_workers_over_100_cases_and_stable_output(config,record):
    records=[{**deepcopy(record),'doc_name':str(i)} for i in range(100)]
    JSONLWriter(config.input_path).write(records)
    active=peak=0;full=asyncio.Event()
    class Tracked(DebateController):
        async def run(self,item):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            if active==40:full.set()
            try:
                await asyncio.wait_for(full.wait(),5)
                await asyncio.sleep(0)
                return await super().run(item)
            finally:active-=1
    def make():return Tracked(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([judge_data()]),config),config)
    summary=await PipelineRunner(config,make).run()
    assert peak==40 and summary['accepted']==100 and summary['pending']==0
    assert [json.loads(x)['doc_name'] for x in config.output_path.read_text().splitlines()]==list(map(str,range(100)))


async def test_unsupported_fewshot_stops_before_examples_used_as_references(config,record):
    from conftest import fewshot_report
    from legal_issue_pipeline.llm.base_client import Completion
    JSONLWriter(config.input_path).write([record])
    seen=[]
    class RejectingClient(FakeClient):
        async def complete(self,messages,schema):
            payload=json.loads(messages[1]['content']);seen.append(payload)
            assert 'examples_to_audit' in payload
            value=fewshot_report(payload['examples_to_audit']);value['checks'][0]['explain_supported']=False
            return Completion(json.dumps(value),{},0,'approval')
    def make():return DebateController(GeneratorAgent(RejectingClient([]),config),JudgeAgent(FakeClient([]),config),config)
    with pytest.raises(LLMError,match='Unsupported few-shot'):
        await PipelineRunner(config,make).run()
    assert len(seen)==1 and config.output_path.read_text()==''
    summary=json.loads((config.audit_dir/'summary.json').read_text())
    assert summary['fewshot_grounding']=='NOT_APPROVED' and summary['pending']==1 and summary['accepted']==0
    assert summary['global_error'] and summary['rejected']==0
