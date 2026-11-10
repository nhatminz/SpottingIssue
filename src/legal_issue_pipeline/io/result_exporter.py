"""Ordered accepted/rejected projections and validation against source + checkpoint."""
from __future__ import annotations

import json
from contextlib import ExitStack

from ..agents.base_agent import reject_duplicate_keys
from ..config import PipelineConfig
from ..validators.output_validator import validate_output
from .jsonl_reader import JSONLReader
from .jsonl_writer import JSONLWriter


class ResultExporter:
    def __init__(self, config: PipelineConfig):
        self.config = config

    @staticmethod
    def require_accepted(row: dict) -> None:
        audit = row["audit"]
        judge = audit.get("final_judge",{})
        if (row["status"] != "COMPLETED" or row["output"] is None
            or audit.get("consensus") != "PASS" or audit.get("required_validations_passed") is not True
            or judge.get("overall_verdict") != "PASS" or judge.get("unresolved_disputes")
            or judge.get("error_codes") or judge.get("generator_visible_feedback") or judge.get("suggested_missing_issues")
            or any(r.get("verdict") != "PASS" or r.get("error_codes") for r in judge.get("per_issue_reviews",[]))
            or audit.get("final_issues") != row["output"].get("issues")):
            raise ValueError("COMPLETED checkpoint lacks final Judge PASS and required validation proof")

    @staticmethod
    def rejected_case(row: dict) -> dict:
        audit = row["audit"]
        if row["status"] != "REJECTED" or row["output"] is not None:
            raise ValueError("REJECTED checkpoint must not store a main-output record")
        if not audit.get("feedback_history") or not audit.get("rejection_reasons"):
            raise ValueError("REJECTED checkpoint lacks reasons or mandatory feedback history")
        return {"case_id":row["case_id"],"input_index":row["index"],"doc_name":audit["doc_name"],
                "status":"REJECTED","rounds":audit["rounds"],"issues":audit["final_issues"],
                "judge_verdict":audit["final_judge"]["overall_verdict"],"stop_reason":audit["stop_reason"],
                "rejection_reasons":audit["rejection_reasons"],"feedback_history":audit["feedback_history"],
                "situation_error":audit["situation_error"],"needs_review":audit.get("needs_review",True)}

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
