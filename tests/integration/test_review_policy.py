import json
import pytest
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from legal_issue_pipeline.llm.base_client import LLMError
from conftest import FakeClient,gen_data,judge_data,critique,response,assessment


def unresolved_factory(config):
    def make():
        final=critique();final["rebuttal_assessments"]=[assessment("UPHOLD")]
        return DebateController(GeneratorAgent(FakeClient([gen_data(),response()]),config),
            JudgeAgent(FakeClient([critique(),final]),config),config)
    return make


@pytest.mark.parametrize("policy",["reject","stop","continue"])
async def test_unapproved_candidates_never_export_even_with_legacy_policy(config,record,policy):
    config.max_debate_rounds=1;config.unresolved_policy=policy
    JSONLWriter(config.input_path).write([record])
    summary=await PipelineRunner(config,unresolved_factory(config)).run()
    assert summary["rejected"]==1 and summary["completed"]==0 and summary["failed"]==0
    assert summary["output_records"]==0 and summary["run_complete"]
    rejected=[json.loads(s) for s in config.rejected_path.read_text().splitlines()]
    assert len(rejected)==1 and rejected[0]["rounds"]==1
    assert rejected[0]["doc_name"]==record["doc_name"] and rejected[0]["feedback_history"]
    def never():raise AssertionError("Cached REJECTED must not be recomputed")
    resumed=await PipelineRunner(config,never).run()
    assert resumed["rejected"]==1 and resumed["output_records"]==0
    assert len(config.rejected_path.read_text().splitlines())==1


async def test_final_judge_api_failure_cannot_emit_initial_candidate(config,record):
    config.max_debate_rounds=1
    JSONLWriter(config.input_path).write([record])
    def make():
        return DebateController(GeneratorAgent(FakeClient([gen_data(),response()]),config),
            JudgeAgent(FakeClient([critique(),LLMError("final evaluation unavailable")]),config),config)
    summary=await PipelineRunner(config,make).run()
    assert summary["failed"]==1 and summary["output_records"]==0
    assert config.output_path.read_text()==""


async def test_validation_disabled_never_approved(config,record):
    config.enable_situation_audit=False;config.max_debate_rounds=1;config.unresolved_policy="continue"
    JSONLWriter(config.input_path).write([record])
    def make():
        return DebateController(GeneratorAgent(FakeClient([gen_data(),gen_data()]),config),JudgeAgent(FakeClient([judge_data(),judge_data()]),config),config)
    summary=await PipelineRunner(config,make).run()
    assert summary["rejected"]==1 and summary["pass_count"]==0 and summary["output_records"]==0
