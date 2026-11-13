from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.config import PipelineConfig, load_config
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.checkpoint import CheckpointManager
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.io.result_exporter import ResultExporter
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.pipeline.runner import PipelineRunner, create_manifest
from conftest import FakeClient,gen_data,judge_data,critique,response,assessment


def make_controller(config, kind="accepted", rounds=1):
    if kind=="accepted":
        gens,judges=[gen_data()],[judge_data()]
    elif kind=="rejected":
        upheld=critique();upheld["rebuttal_assessments"]=[assessment("UPHOLD")]
        gens=[gen_data()]+[response() for _ in range(rounds)]
        judges=[critique()]+[deepcopy(upheld) for _ in range(rounds)]
    else:
        gens,judges=[LLMError("API unavailable")],[]
    return DebateController(GeneratorAgent(FakeClient(gens),config),JudgeAgent(FakeClient(judges),config),config)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def snapshot(config):
    preflight=PipelineRunner(config).preflight()
    return CheckpointManager.read_records(config.checkpoint_dir,create_manifest(config,preflight["input_sha256"]))


@pytest.mark.parametrize("rounds",[1,5,8,10])
async def test_max_rounds_rejects_and_final_judge_is_still_required(config,record,rounds):
    config.max_debate_rounds=rounds;config.stop_on_stagnation=False
    controller=make_controller(config,"rejected",rounds)
    result=await controller.run(record)
    assert result.status.value=="REJECTED"
    assert result.audit["rounds"]==rounds
    assert len(controller.generator.client.messages)==rounds+1
    assert len(controller.judge.client.messages)==rounds+1
    assert result.audit["stop_reason"]=="MAX_ROUNDS"


async def test_rejection_between_acceptances_does_not_block_order_or_resume(config,record):
    config.max_debate_rounds=1
    originals=[{**deepcopy(record),"doc_name":name} for name in ["first","rejected","last"]]
    JSONLWriter(config.input_path).write(originals)
    kinds=iter(["accepted","rejected","accepted"])
    summary=await PipelineRunner(config,lambda:make_controller(config,next(kinds))).run()
    assert summary["total_input_records"]==3 and summary["selected_records"]==3
    assert (summary["accepted"],summary["rejected"],summary["failed"],summary["output_records"])==(2,1,0,2)
    assert summary["run_complete"]
    assert [r["doc_name"] for r in read_jsonl(config.output_path)]==["first","last"]
    rejected=read_jsonl(config.rejected_path)
    assert [r["doc_name"] for r in rejected]==["rejected"]
    assert rejected[0]["issues"]==[gen_data()["issues"][0]["issue_text"]]
    assert rejected[0]["rejection_reasons"] and len(rejected[0]["feedback_history"])==2
    assert critique()["generator_visible_feedback"][0]["explanation"] in rejected[0]["rejection_reasons"]
    assert ResultExporter(config).validate(snapshot(config))["records"]==2
    def never():raise AssertionError("Terminal completed/rejected case was recomputed")
    config.output_path.write_text("broken interrupted projection")
    config.rejected_path.write_text("broken interrupted projection")
    resumed=await PipelineRunner(config,never).run()
    assert resumed["accepted"]==2 and resumed["rejected"]==1
    assert len(read_jsonl(config.output_path))==2 and len(read_jsonl(config.rejected_path))==1
    assert len(read_jsonl(config.audit_dir/"states.jsonl"))==9


async def test_all_rejected_is_finished_and_empty_main_output_is_valid(config,record):
    config.max_debate_rounds=1
    JSONLWriter(config.input_path).write([record])
    summary=await PipelineRunner(config,lambda:make_controller(config,"rejected")).run()
    assert summary["run_complete"] and summary["rejected"]==1
    assert config.output_path.read_text()==""
    assert ResultExporter(config).validate(snapshot(config))["records"]==0


async def test_feedback_history_remains_when_save_history_disabled(config,record):
    config.max_debate_rounds=1;config.save_debate_history=False
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,lambda:make_controller(config,"rejected")).run()
    rows=snapshot(config)
    assert rows[0]["audit"]["history"]==[] and rows[0]["output"] is None
    assert read_jsonl(config.rejected_path)[0]["feedback_history"][-1]["judge"]["rebuttal_assessments"][0]["decision"]=="UPHOLD"


@pytest.mark.parametrize("error",[LLMError("API unavailable"),LLMError("API timeout"),"{malformed JSON"])
async def test_technical_errors_are_failed_and_not_rejected(config,record,error):
    JSONLWriter(config.input_path).write([record])
    def factory():
        return DebateController(GeneratorAgent(FakeClient([error]),config),JudgeAgent(FakeClient([]),config),config)
    summary=await PipelineRunner(config,factory).run()
    assert summary["failed"]==1 and summary["rejected"]==0 and not summary["run_complete"]
    assert config.rejected_path.read_text()==config.output_path.read_text()==""
    with pytest.raises(ValueError,match="Run incomplete"):
        ResultExporter(config).validate(snapshot(config))


async def test_pass_with_situation_error_true_is_retained(config,record):
    JSONLWriter(config.input_path).write([record])
    data=judge_data()
    data["situation_audit"]["missing_facts"]=[dict(fact="Thiếu dữ kiện",markdown_evidence_quotes=["PRIVATE_MARKDOWN_ONLY_FACT"],
        material=True,importance_reason="Quan trọng",affected_issue="Vấn đề bị ảnh hưởng",equivalent_in_situation=False,
        equivalence_assessment="Không có trong situation")]
    def factory():
        return DebateController(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([data]),config),config)
    summary=await PipelineRunner(config,factory).run()
    assert summary["accepted"]==1 and summary["rejected"]==0 and summary["situation_error_true"]==1
    assert read_jsonl(config.output_path)[0]["situation_error"] is True
    assert config.rejected_path.read_text()==""


async def test_rejected_file_records_final_issues_not_older_best_candidate(config,record):
    config.max_debate_rounds=1
    JSONLWriter(config.input_path).write([record])
    revised=response()
    revised["issues"][0]["issue_text"]=revised["issues"][0]["issue_text"].replace(" khi "," trong trường hợp ")
    def factory():
        # Unchanged evidence, but more adverse codes -> older candidate ranks best.
        final=critique();final["per_issue_reviews"][0]["error_codes"].append("LOW_RELEVANCE")
        final["rebuttal_assessments"]=[assessment("UPHOLD")]
        return DebateController(GeneratorAgent(FakeClient([gen_data(),revised]),config),JudgeAgent(FakeClient([critique(),final]),config),config)
    await PipelineRunner(config,factory).run()
    assert snapshot(config)[0]["audit"]["selected_evaluation"]==0
    assert read_jsonl(config.rejected_path)[0]["issues"]==[revised["issues"][0]["issue_text"]]


async def test_filtered_validation_uses_indices_with_duplicate_doc_names(config,record):
    config.start_index=1;config.limit=2;config.max_debate_rounds=1
    # Same doc_name at every position; source fields differ, so matching by name fails.
    JSONLWriter(config.input_path).write([{**deepcopy(record),"original_index":i} for i in range(4)])
    kinds=iter(["rejected","accepted"])
    await PipelineRunner(config,lambda:make_controller(config,next(kinds))).run()
    assert read_jsonl(config.output_path)[0]["original_index"]==2
    counts=ResultExporter(config).validate(snapshot(config))
    assert (counts["records"],counts["rejected"],counts["selected_records"])==(1,1,2)


async def test_concurrent_filtering_and_error_counts(config,record):
    config.max_workers=3;config.max_debate_rounds=1;config.fail_on_record_error=False
    JSONLWriter(config.input_path).write([{**record,"doc_name":str(i)} for i in range(6)])
    class DelayedController(DebateController):
        async def run(self,record):
            await asyncio.sleep(0.005*(6-int(record["doc_name"])))
            return await super().run(record)
    kinds=iter(["accepted","rejected","failed","accepted","rejected","accepted"])
    def factory():
        c=make_controller(config,next(kinds))
        return DelayedController(c.generator,c.judge,config)
    summary=await PipelineRunner(config,factory).run()
    assert (summary["accepted"],summary["rejected"],summary["failed"],summary["pending"])==(3,2,1,0)
    assert summary["accepted"]+summary["rejected"]+summary["failed"]==summary["selected_records"]
    assert [r["doc_name"] for r in read_jsonl(config.output_path)]==["0","3","5"]
    assert [r["doc_name"] for r in read_jsonl(config.rejected_path)]==["1","4"]


@pytest.mark.parametrize("target",["main","rejected"])
async def test_validation_detects_candidate_in_main_and_missing_rejection(config,record,target):
    config.max_debate_rounds=1
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,lambda:make_controller(config,"rejected")).run()
    if target=="main":
        JSONLWriter(config.output_path).write([{**record,"issues":[],"situation_error":False}])
    else:
        config.rejected_path.write_text("")
    with pytest.raises(ValueError):
        ResultExporter(config).validate(snapshot(config))


@pytest.mark.parametrize("path_name",["input_path","output_path"])
def test_rejected_path_cannot_overwrite_input_or_main(config,path_name):
    values=config.model_dump();values["rejected_path"]=getattr(config,path_name)
    with pytest.raises(ValueError,match="differ"):
        PipelineConfig(**values)


def test_shell_env_rejected_path_and_legacy_policy(monkeypatch,tmp_path):
    monkeypatch.setenv("OUTPUT_PATH",str(tmp_path/"nested/issues.jsonl"))
    monkeypatch.delenv("REJECTED_PATH",raising=False)
    monkeypatch.setenv("UNRESOLVED_POLICY","continue")
    config=load_config()
    assert config.rejected_path==tmp_path/"nested/rejected_cases.jsonl"
    assert config.unresolved_policy=="reject"


@pytest.mark.parametrize("kind",["accepted","rejected"])
async def test_cli_validate_allows_fewer_output_lines_after_quality_filter(config,record,monkeypatch,capsys,kind):
    from legal_issue_pipeline.cli import main
    config.max_debate_rounds=1
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,lambda:make_controller(config,kind)).run()
    monkeypatch.setattr("legal_issue_pipeline.cli.load_config",lambda:config)
    monkeypatch.setattr("sys.argv",["legal-issues","validate"])
    assert main()==0
    result=json.loads(capsys.readouterr().out)
    assert result["valid"] is True
    assert result["records"]==(kind=="accepted")
    assert result["rejected"]==(kind=="rejected")


async def test_cli_run_treats_all_rejected_as_finished_not_error(config,record,monkeypatch,capsys):
    from legal_issue_pipeline.cli import main
    config.max_debate_rounds=1
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,lambda:make_controller(config,"rejected")).run()
    monkeypatch.setattr("legal_issue_pipeline.cli.load_config",lambda:config)
    monkeypatch.setattr("sys.argv",["legal-issues","run"])
    # Real CLI loop reads the durable rejected checkpoint without an inference.
    exit_code=await asyncio.to_thread(main)
    assert exit_code==0
    assert '"rejected": 1' in capsys.readouterr().out


@pytest.mark.parametrize("change",["input","model","prompt"])
async def test_rejected_checkpoint_detects_changes_and_requires_new_run(config,record,tmp_path,change):
    import shutil
    config.max_debate_rounds=1
    prompt_dir=tmp_path/"prompt-copy";shutil.copytree(config.prompt_dir,prompt_dir);config.prompt_dir=prompt_dir
    JSONLWriter(config.input_path).write([record])
    await PipelineRunner(config,lambda:make_controller(config,"rejected")).run()
    if change=="input":
        JSONLWriter(config.input_path).write([{**record,"changed_field":1}])
    elif change=="model":
        config.gen.model="changed-model"
    else:
        p=config.prompt_dir/"generator_system.md";p.write_text(p.read_text()+"\nchanged")
    with pytest.raises(ValueError,match="fingerprint mismatch"):
        await PipelineRunner(config,lambda:make_controller(config)).run()


async def test_stagnation_rejects_with_actual_round_count(config,record):
    config.max_debate_rounds=8;config.max_stagnant_rounds=1
    JSONLWriter(config.input_path).write([record])
    summary=await PipelineRunner(config,lambda:make_controller(config,"rejected",8)).run()
    rejected=read_jsonl(config.rejected_path)[0]
    assert summary["rejected"]==1 and summary["run_complete"]
    assert rejected["stop_reason"]=="STAGNATION" and rejected["rounds"]<8
