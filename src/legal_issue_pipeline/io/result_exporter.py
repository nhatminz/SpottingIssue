"""Ordered accepted/rejected projections and validation against source + checkpoint."""
from __future__ import annotations

import json
from contextlib import ExitStack

from ..agents.base_agent import reject_duplicate_keys
from ..config import PipelineConfig
from ..validators.output_validator import validate_output
from ..validators.judge_validator import scope_rubric_passes
from ..schemas import GeneratorOutput, JudgeOutput, CONTRACT_VERSION
from ..validators.format_validator import candidate_errors
from .jsonl_reader import JSONLReader
from .jsonl_writer import JSONLWriter


class ResultExporter:
    def __init__(self, config: PipelineConfig):
        self.config = config

    @staticmethod
    def require_accepted(row: dict) -> None:
        audit = row["audit"]
        judge = JudgeOutput.model_validate_json(json.dumps(audit.get("final_judge",{}))).model_dump(mode="json")
        if (audit.get("contract") != CONTRACT_VERSION or row["status"] != "COMPLETED" or row["output"] is None
            or audit.get("consensus") != "PASS" or audit.get("required_validations_passed") is not True
            or judge.get("overall_verdict") != "PASS" or judge.get("unresolved_disputes")
            or not scope_rubric_passes(judge)
            or judge.get("error_codes") or judge.get("generator_visible_feedback")
            or any(r.get("verdict") != "PASS" or r.get("error_codes") for r in judge.get("per_issue_reviews",[]))
            or audit.get("final_issues") != row["output"].get("issues")
            or audit.get("final_explain") != row["output"].get("explain")):
            raise ValueError("COMPLETED checkpoint lacks final Judge PASS and required validation proof")
        generated = GeneratorOutput.model_validate_json(json.dumps(audit.get("final_generator", {})))
        if ([i.issue_text for i in generated.issues] != row["output"]["issues"] or
            [i.explain for i in generated.issues] != row["output"]["explain"] or
            len(generated.private_judicial_support) != len(generated.issues) or
            len({i.issue_id for i in generated.issues}) != len(generated.issues) or
            {r["issue_id"] for r in judge["per_issue_reviews"]} != {i.issue_id for i in generated.issues} or
            {s.issue_id for s in generated.private_judicial_support} != {i.issue_id for i in generated.issues} or
            any(not s.judicial_relevance_confirmed or not s.conclusion_consistent for s in generated.private_judicial_support)):
            raise ValueError("Missing Generator judicial-scope proof or issue/explain alignment")

    @staticmethod
    def rejected_case(row: dict) -> dict:
        audit = row["audit"]
        if row["status"] != "REJECTED" or row["output"] is not None:
            raise ValueError("REJECTED checkpoint must not store a main-output record")
        if not audit.get("feedback_history") or not audit.get("rejection_reasons"):
            raise ValueError("REJECTED checkpoint lacks reasons or mandatory feedback history")
        return {"case_id":row["case_id"],"input_index":row["index"],"doc_name":audit["doc_name"],
                "status":"REJECTED","rounds":audit["rounds"],"issues":audit["final_issues"],"explain":audit["final_explain"],
                "judge_verdict":audit["final_judge"]["overall_verdict"],"stop_reason":audit["stop_reason"],
                "rejection_reasons":audit["rejection_reasons"],"feedback_history":audit["feedback_history"],
                "needs_review":audit.get("needs_review",True)}

    def write(self, rows: list[dict]) -> int:
        accepted, rejected = [], []
        for row in sorted(rows,key=lambda r:r["index"]):
            if row["status"] == "COMPLETED":
                self.require_accepted(row)
                accepted.append(row["output"])
            elif row["status"] == "REJECTED":
                rejected.append(self.rejected_case(row))
        # Each file is atomic; after a crash both are rebuilt from durable SQLite.
        JSONLWriter(self.config.output_path).write(accepted)
        JSONLWriter(self.config.rejected_path).write(rejected)
        return len(accepted)

    @staticmethod
    def _next_object(stream, label: str) -> dict:
        line = stream.readline()
        if not line:
            raise ValueError(f"{label}: missing checkpoint record")
        def reject_constant(_):
            raise ValueError("Non-finite JSON number")
        value = json.loads(line,object_pairs_hook=reject_duplicate_keys,parse_constant=reject_constant)
        if not isinstance(value,dict):
            raise ValueError(f"{label}: expected JSON object")
        return value

    def validate(self, rows: list[dict], require_finished: bool = True) -> dict:
        by_index = {r["index"]:r for r in rows}
        counts = {"records":0,"rejected":0,"failed":0,"pending":0,"selected_records":0}
        with ExitStack() as stack:
            output = stack.enter_context(self.config.output_path.open(encoding="utf-8"))
            rejected = stack.enter_context(self.config.rejected_path.open(encoding="utf-8"))
            for record in JSONLReader(self.config.input_path):
                if record.index < self.config.start_index:
                    continue
                if self.config.limit and record.index >= self.config.start_index+self.config.limit:
                    break
                counts["selected_records"] += 1
                row = by_index.pop(record.index,None)
                if row is None or row["case_id"] != record.case_id:
                    raise ValueError("Checkpoint does not match selected input records")
                if row["status"] == "COMPLETED":
                    self.require_accepted(row)
                    generated = GeneratorOutput.model_validate_json(json.dumps(row["audit"]["final_generator"]))
                    if candidate_errors(generated,record.data["benchmark_seed"]["facts_clean"],self.config):
                        raise ValueError("Cached Generator candidate fails facts/format validation")
                    emitted = self._next_object(output,"Main output")
                    validate_output(record.data,emitted)
                    if emitted != row["output"]:
                        raise ValueError("Main output differs from accepted checkpoint or input order")
                    counts["records"] += 1
                elif row["status"] == "REJECTED":
                    emitted = self._next_object(rejected,"Rejected cases")
                    if emitted != self.rejected_case(row) or emitted["doc_name"] != record.data["doc_name"]:
                        raise ValueError("Rejected cases differ from checkpoint or input order")
                    counts["rejected"] += 1
                elif row["status"] == "FAILED":
                    counts["failed"] += 1
                elif row["status"] in ["PENDING","RUNNING"]:
                    counts["pending"] += 1
                else:
                    raise ValueError(f"Unsupported checkpoint status: {row['status']}")
            if by_index or output.read() or rejected.read():
                raise ValueError("Unexpected extra checkpoint or JSONL records")
        if require_finished and (counts["failed"] or counts["pending"]):
            raise ValueError("Run incomplete: FAILED/PENDING/RUNNING cases remain")
        return {"valid":True,**counts}
