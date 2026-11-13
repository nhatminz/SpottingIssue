import asyncio
import json
from copy import deepcopy

import pytest

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from legal_issue_pipeline.schemas import GeneratorOutput, JudgeOutput
from legal_issue_pipeline.validators.format_validator import candidate_errors
from legal_issue_pipeline.validators.judge_validator import scope_rubric_passes
from conftest import FakeClient, SITUATION, gen_data, issue_data, judge_data


async def test_all_roles_receive_the_same_academic_definitions_and_five_criteria(config, record):
    generator = GeneratorAgent(FakeClient([gen_data()]), config)
    judge = JudgeAgent(FakeClient([{"issues": []}, judge_data()]), config)
    await judge.discover(record["situation"])
    current = await generator.generate(record["situation"])
    await judge.evaluate(record, current, None, None, [], [])
    shared = (config.prompt_dir / "benchmark_scope.md").read_text()
    for messages in generator.client.messages + judge.client.messages:
        system = messages[0]["content"]
        assert shared in system
        for criterion in ["Legal Question", "Fact Grounding", "Judicial Relevance", "Independence", "Non-conclusiveness"]:
            assert criterion in system
        assert "Issue step of IRAC" in system
        assert "ROUTINE_PROCEDURAL" in system and "CORE_ISSUE" in system
        assert "independence removal test" in system.lower()
        assert "Vietnamese noun phrase" in system
    assert candidate_errors(current, record["situation"], config) == []


def test_supporting_premise_in_court_reasoning_is_still_excluded(config, record):
    court = "Chị B đã bị tuyên bố mất tích, là căn cứ xem xét yêu cầu ly hôn của anh A."
    record["markdown"] += " " + court
    data = judge_data("REVISE")
    review = deepcopy(data["per_issue_reviews"][0])
    review.update(issue_id="I2", classification="SUPPORTING_FACT", court_scope_confirmed=False, related_issue_ids=["I1"],
        verdict="REMOVE", error_codes=["SUPPORTING_FACT"], markdown_evidence_quotes=[court],
        explanation="Không đạt Independence: tình trạng mất tích là tiền đề cho ly hôn, không phải yêu cầu tuyên bố mất tích mới.")
    data["per_issue_reviews"].append(review)
    data["rubric"]["legal_relevance"] = "FAIL"
    data["error_codes"] = ["SUPPORTING_FACT"]
    data["generator_visible_feedback"] = [dict(feedback_id="F1", issue_ids=["I2", "I1"], error_code="SUPPORTING_FACT",
        action="REMOVE", situation_evidence_quotes=[SITUATION], explanation="Bỏ nhãn phụ và giữ tình tiết trong nhãn ly hôn.")]
    supporting = issue_data()
    supporting.update(issue_id="I2", issue_text="Việc xác định tư cách người mất tích của chị B khi chị B đã bị Tòa án tuyên bố mất tích",
        focus="Việc xác định tư cách", subject_action="người mất tích của chị B")
    current = GeneratorOutput.model_validate_json(json.dumps({"issues": [issue_data(), supporting], "responses_to_feedback": []}))
    judgment = JudgeOutput.model_validate_json(json.dumps(data))
    JudgeAgent(FakeClient([]), config).validate_judgment(judgment, record, current, None)
    assert not scope_rubric_passes(judgment)
    assert judgment.per_issue_reviews[1].markdown_evidence_quotes == [court]


async def test_exceptional_procedure_can_pass_without_an_objection(config, record):
    # Synthetic source: a distinctive international element, no stated dispute over jurisdiction.
    situation = "Anh A yêu cầu ly hôn chị B. Chị B đang cư trú tại nước ngoài và chưa xác định được địa chỉ."
    court = "Tòa án xác định thẩm quyền giải quyết yêu cầu ly hôn có yếu tố nước ngoài trong trường hợp chưa rõ địa chỉ của chị B."
    record["situation"] = situation
    divorce_court = "Tòa án chấp nhận yêu cầu ly hôn của anh A đối với chị B."
    record["markdown"] = situation + "\n# Nhận định và quyết định\n" + court + " " + divorce_court
    procedural = dict(issue_id="I2", issue_text="Thẩm quyền giải quyết yêu cầu ly hôn của anh A đối với chị B khi chị B cư trú tại nước ngoài và chưa xác định được địa chỉ",
        focus_group="PROCEDURE", focus="Thẩm quyền", subject_action="giải quyết yêu cầu ly hôn của anh A đối với chị B",
        decisive_fact="chị B cư trú tại nước ngoài và chưa xác định được địa chỉ", situation_evidence_quotes=[situation], importance="CORE")
    divorce = issue_data()
    divorce.update(issue_text="Việc xác định quyền yêu cầu ly hôn của anh A khi chị B đang cư trú tại nước ngoài và chưa xác định được địa chỉ",
        decisive_fact="chị B đang cư trú tại nước ngoài và chưa xác định được địa chỉ", situation_evidence_quotes=[situation])
    initial = {"issues": [divorce, procedural], "responses_to_feedback": []}
    judgment = judge_data()
    judgment["per_issue_reviews"][0]["situation_evidence_quotes"] = [situation]
    judgment["per_issue_reviews"][0]["markdown_evidence_quotes"] = [divorce_court]
    judgment["coverage_analysis"][0].update(issue_text=divorce["issue_text"], situation_evidence_quotes=[situation], markdown_evidence_quotes=[divorce_court])
    review = deepcopy(judgment["per_issue_reviews"][0])
    review.update(issue_id="I2", markdown_evidence_quotes=[court], explanation="Thẩm quyền có yếu tố nước ngoài cần được xác định độc lập; không cần có phản đối giữa các bên.")
    judgment["per_issue_reviews"].append(review)
    judgment["coverage_analysis"].append(dict(coverage_id="C2", issue_text=procedural["issue_text"], situation_evidence_quotes=[situation],
        markdown_evidence_quotes=[court], court_scope_confirmed=True, matched_issue_ids=["I2"]))
    controller = DebateController(GeneratorAgent(FakeClient([initial]), config), JudgeAgent(FakeClient([judgment]), config), config)
    result = await controller.run(record)
    assert result.status.value == "COMPLETED"
    assert result.issues == [divorce["issue_text"], procedural["issue_text"]]


async def test_100_records_reach_60_workers_and_keep_input_order(config, record):
    config.max_workers = 60
    config.max_concurrent_requests = 60
    config.batch_size = 100
    records = [{**deepcopy(record), "doc_name": f"case-{index:03}"} for index in range(100)]
    JSONLWriter(config.input_path).write(records)
    active = peak = 0
    started = []
    full_wave = asyncio.Event()
    class TrackedController(DebateController):
        async def run(self, item):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.append(item["doc_name"])
            if active == 60:
                full_wave.set()
            try:
                await asyncio.wait_for(full_wave.wait(), timeout=5)
                await asyncio.sleep(0)
                return await super().run(item)
            finally:
                active -= 1
    def factory():
        return TrackedController(GeneratorAgent(FakeClient([gen_data()]), config),
                                 JudgeAgent(FakeClient([judge_data()]), config), config)
    summary = await PipelineRunner(config, factory).run()
    assert peak == 60 and len(started) == 100
    assert summary["accepted"] == 100 and summary["failed"] == 0 and summary["pending"] == 0
    assert summary["run_complete"] is True
    assert [json.loads(line)["doc_name"] for line in config.output_path.read_text().splitlines()] == [item["doc_name"] for item in records]
