import asyncio
import json
from copy import deepcopy
import pytest
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_reader import JSONLReader
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from legal_issue_pipeline.validators.output_validator import make_output
from conftest import FakeClient,gen_data,judge_data


def factory(config,fail=False):
    return lambda: DebateController(GeneratorAgent(FakeClient([LLMError("server unavailable")] if fail else [gen_data()]),config),
                                   JudgeAgent(FakeClient([judge_data()]),config),config)


async def test_read_preserve_and_resume_without_duplicates(config,record):
    records=[deepcopy(record) for _ in range(3)]
    records[1]["doc_name"]="case-2"
    JSONLWriter(config.input_path).write(records)
    read=list(JSONLReader(config.input_path))
    assert [r.data for r in read]==records
    assert len({r.case_id for r in read})==3
    summary=await PipelineRunner(config,factory(config)).run()
    assert summary["completed"]==3 and summary["output_records"]==3
    output=[json.loads(s) for s in config.output_path.read_text().splitlines()]
    for original,result in zip(records,output):
        assert result==make_output(original,result["issues"],False)
        assert type(result["situation_error"]) is bool
        assert set(result)==set(original)|{"issues","situation_error"}
    def never_called():raise AssertionError("Completed record recomputed")
    resumed=await PipelineRunner(config,never_called).run()
    assert resumed["completed"]==3
    assert len(config.output_path.read_text().splitlines())==3
    states=[json.loads(s)["status"] for s in (config.audit_dir/"states.jsonl").read_text().splitlines()]
    assert "PENDING" in states and "RUNNING" in states and "COMPLETED" in states


async def test_failed_records_have_no_fabricated_labels_and_resume(config,record):
    JSONLWriter(config.input_path).write([record])
    summary=await PipelineRunner(config,factory(config,True)).run()
    assert summary["failed"]==1 and not summary["run_complete"]
    assert config.output_path.read_text()==""
    assert (config.log_dir/"failures.jsonl").read_text().strip()
    summary=await PipelineRunner(config,factory(config)).run()
    assert summary["completed"]==1 and summary["failed"]==0


async def test_concurrent_order_and_independent_clients(config,record):
    config.max_workers=3;config.max_concurrent_requests=2
    records=[]
    for n in range(6):
        r=deepcopy(record);r["doc_name"]=str(n);records.append(r)
    JSONLWriter(config.input_path).write(records)
    instances=[]
    class DelayedController(DebateController):
        async def run(self,record):
            await asyncio.sleep(0.01*(6-int(record["doc_name"])))
            return await super().run(record)
    def make():
        c=DelayedController(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([judge_data()]),config),config)
        instances.append(c);return c
    summary=await PipelineRunner(config,make).run()
    assert summary["completed"]==6
    assert [json.loads(s)["doc_name"] for s in config.output_path.read_text().splitlines()]==list(map(str,range(6)))
    assert len({id(c.generator.client) for c in instances}|{id(c.judge.client) for c in instances})==12


@pytest.mark.parametrize("change",["prompt","config"])
async def test_resume_fingerprint_changes_detected(config,record,tmp_path,change):
    import shutil
    prompt_dir=tmp_path/"prompts";shutil.copytree(config.prompt_dir,prompt_dir);config.prompt_dir=prompt_dir
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,factory(config)).run()
    if change=="config":config.gen.model="different-model"
    else:
        path=prompt_dir/"generator_system.md";path.write_text(path.read_text()+"\nnew prompt")
    with pytest.raises(ValueError,match="fingerprint mismatch"):
        await PipelineRunner(config,factory(config)).run()


async def test_input_fingerprint_change_detected(config,record):
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,factory(config)).run()
    record["other"]=1;JSONLWriter(config.input_path).write([record])
    with pytest.raises(ValueError,match="fingerprint mismatch"):
        await PipelineRunner(config,factory(config)).run()


async def test_fail_continue_exports_accepted_and_resume_restores_order(config,record):
    config.fail_on_record_error=False;config.max_workers=2
    JSONLWriter(config.input_path).write([record,{**record,"doc_name":"second"}])
    count=0
    def make():
        nonlocal count
        count+=1
        return factory(config,fail=count==1)()
    summary=await PipelineRunner(config,make).run()
    assert summary["failed"]==1 and summary["completed"]==1
    assert summary["output_records"]==1
    assert json.loads(config.output_path.read_text())["doc_name"]=="second"
    summary=await PipelineRunner(config,factory(config)).run()
    assert summary["output_records"]==2


async def test_no_overwrite_input_or_unrelated_output(config,record):
    JSONLWriter(config.input_path).write([record])
    config.output_path.write_text("important existing data")
    with pytest.raises(ValueError,match="Existing output"):
        await PipelineRunner(config,factory(config)).run()
    assert config.output_path.read_text()=="important existing data"


async def test_dry_run_no_output_or_checkpoint(config,record):
    JSONLWriter(config.input_path).write([record]);config.dry_run=True
    summary=await PipelineRunner(config,lambda: (_ for _ in ()).throw(AssertionError())).run()
    assert summary["dry_run"]
    assert not config.output_path.exists() and not config.checkpoint_dir.exists()
