from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from ..agents.generator import GeneratorAgent
from ..agents.judge import JudgeAgent
from ..config import PipelineConfig, digest
from ..debate.controller import DebateController
from ..io.checkpoint import CheckpointManager
from ..io.jsonl_reader import JSONLReader, InputRecord
from ..io.jsonl_writer import JSONLWriter, atomic_text
from ..io.result_exporter import ResultExporter
from ..io.fewshot import FewShotBank
from ..schemas import FewShotValidation
from ..llm.client_factory import ClientFactory
from ..llm.adapters import adapter_for
from ..validators.output_validator import make_output

log = logging.getLogger(__name__)


def create_manifest(config: PipelineConfig, input_hash: str) -> dict:
    prompt_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(config.prompt_dir.glob("*.md"))}
    if not {"generator_system.md", "generator_revision.md", "judge_system.md", "judge_reconsideration.md",
            "benchmark_scope.md", "judge_blind_discovery.md", "generator_fewshot_validation.md"} <= prompt_hashes.keys():
        raise ValueError("Missing required prompt files")
    source_root = Path(__file__).resolve().parents[1]
    code_hash = digest({str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_root.rglob("*.py"))})
    return {"input_sha256": input_hash, "config_sha256": digest(config.semantic_dict()), "prompt_sha256": prompt_hashes,
            "code_sha256": code_hash, "export_policy":"fac_facts_only_v3",
            "fewshot_sha256":hashlib.sha256(config.fewshot_path.read_bytes()).hexdigest(), "output_path": str(config.output_path),
            "rejected_path":str(config.rejected_path),"audit_dir": str(config.audit_dir), "log_dir": str(config.log_dir)}


class PipelineRunner:
    def __init__(self, config: PipelineConfig, controller_factory: Callable[[], DebateController] | None = None):
        self.config = config
        self.controller_factory = controller_factory
        self.client_factory = None
        self.stop_requested = asyncio.Event()
        self.fewshot = None
        self.global_error = None

    def _selected(self, reader):
        for record in reader:
            if record.index < self.config.start_index:
                continue
            if self.config.limit and record.index >= self.config.start_index+self.config.limit:
                break
            yield record

    def preflight(self) -> dict:
        # Catch unsupported thinking settings before creating checkpoints or starting any case.
        for role in ["gen", "judge"]:
            try:
                agent = getattr(self.config, role)
                _, effective = adapter_for(agent).parameters(agent, self.config)
            except ValueError as exc:
                raise ValueError(f"{role} configuration: {exc}") from None
            log.info("%s backend=%s thinking=%s requested_effort=%s effective_effort=%s", role, agent.backend,
                     effective["thinking_enabled"], effective["requested_effort"], effective["effective_effort"])
        reader = JSONLReader(self.config.input_path)
        # Full schema validation occurs before any expensive inference or output mutation.
        total = sum(1 for _ in reader)
        selected = max(0, min(total-self.config.start_index, self.config.limit or total))
        if not selected:
            raise ValueError("Selection contains no records")
        self.fewshot = FewShotBank(self.config.fewshot_path)
        overlaps = [{"input_index": r.index, "doc_name": r.data["doc_name"], "excluded_examples": self.fewshot.for_record(r.data)[1]}
                    for r in self._selected(reader) if self.fewshot.for_record(r.data)[1]]
        return {"total_input_records": total, "selected_records": selected, "input_sha256": reader.fingerprint(),
                "fewshot_examples":len(self.fewshot.examples), "fewshot_overlaps": overlaps,
                "fewshot_grounding":"runtime Generator semantic check required before examples are used"}

    def _make_controller(self):
        if self.controller_factory:
            return self.controller_factory()
        if self.client_factory is None:
            self.client_factory = ClientFactory(self.config)
        return DebateController(GeneratorAgent(self.client_factory.create("gen"), self.config, self.fewshot),
                                JudgeAgent(self.client_factory.create("judge"), self.config), self.config)

    async def _process(self, record: InputRecord, checkpoints: CheckpointManager, workers: asyncio.Semaphore):
        async with workers:
            existing = checkpoints.get(record.index)
            if existing and existing["status"] in ["COMPLETED", "REJECTED"]:
                return
            if self.stop_requested.is_set():
                return
            controller = None
            checkpoints.set(record.index, record.case_id, "RUNNING")
            try:
                controller = self._make_controller()
                result = await controller.run(record.data)
                if result.status.value not in ["COMPLETED","REJECTED"]:
                    raise ValueError("Debate must return COMPLETED or REJECTED; technical errors must raise")
                output = make_output(record.data, result.issues, result.explain) if result.status.value == "COMPLETED" else None
                audit = {**result.audit, "case_id": record.case_id, "input_index": record.index,"doc_name":record.data["doc_name"],
                         "api_calls": {"generator": getattr(controller.generator.client, "calls", []),
                                       "judge": getattr(controller.judge.client, "calls", [])}}
                row = {"index":record.index,"case_id":record.case_id,"status":result.status.value,"output":output,"audit":audit}
                if result.status.value == "COMPLETED":
                    ResultExporter.require_accepted(row)
                else:
                    ResultExporter.rejected_case(row)
                checkpoints.set(record.index, record.case_id, result.status.value, output, audit)
                atomic_text(self.config.audit_dir/(record.case_id+".json"),json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
                log.info("case=%s status=%s issues=%d rounds=%s", record.case_id,result.status.value,len(result.issues),audit.get("rounds"))
            except asyncio.CancelledError:
                # RUNNING is retried safely when resumed; completed peers stay durable.
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                # Client exceptions are sanitized. Also redact configured secret values.
                for agent in [self.config.gen, self.config.judge]:
                    key = agent.api_key.get_secret_value()
                    if key and key != "EMPTY":
                        error = error.replace(key, "<redacted>")
                audit = {"case_id": record.case_id, "input_index": record.index,"doc_name":record.data["doc_name"],"status": "FAILED", "error": error,
                         "blind_discovery":controller.blind_discovery.model_dump(mode="json") if controller and controller.blind_discovery else None,
                         "history": getattr(controller,"trace",[]) if self.config.save_debate_history else [],
                         "api_calls": {role: getattr(getattr(controller, name, None).client, "calls", [])
                                       for role,name in [("generator","generator"),("judge","judge")]} if controller else {},
                         "requests": {"generator":controller.generator.request_metrics,"judge":controller.judge.request_metrics} if controller else {}}
                checkpoints.set(record.index,record.case_id,"FAILED",audit=audit,error=error)
                atomic_text(self.config.audit_dir/(record.case_id+".json"),json.dumps(audit,ensure_ascii=False,indent=2)+"\n")
                log.error("case=%s failed: %s",record.case_id,error)
                if self.config.fail_on_record_error:
                    self.stop_requested.set()
            finally:
                if controller:
                    await asyncio.gather(controller.generator.client.close(), controller.judge.client.close())

    def _materialize(self, checkpoints: CheckpointManager) -> int:
        return ResultExporter(self.config).write(checkpoints.records())

    def _export_audit(self, checkpoints, preflight, manifest, exported) -> dict:
        rows = checkpoints.records()
        for row in rows:
            if row["audit"]:
                atomic_text(self.config.audit_dir/(row["case_id"]+".json"),json.dumps(row["audit"],ensure_ascii=False,indent=2)+"\n")
        JSONLWriter(self.config.audit_dir/"records.jsonl").write({"case_id": r["case_id"], "input_index": r["index"], "status": r["status"],
            "doc_name":r["audit"].get("doc_name"),
            "issue_count": len(r["audit"].get("final_issues",[])),
            **{k:r["audit"].get(k) for k in ["stop_reason","rounds","consensus","early_stop","generator_contests","judge_changes","selected_evaluation"]}} for r in rows)
        JSONLWriter(self.config.log_dir/"failures.jsonl").write({**{k:r[k] for k in ["case_id","index","error"]},"doc_name":r["audit"].get("doc_name"),"status":"FAILED"} for r in rows if r["status"] == "FAILED")
        JSONLWriter(self.config.audit_dir/"states.jsonl").write(checkpoints.events())
        successful = [r for r in rows if r["status"] == "COMPLETED"]
        rejected_count = sum(r["status"] == "REJECTED" for r in rows)
        terminal = [r for r in rows if r["status"] in ["COMPLETED","REJECTED"]]
        count = len(successful)
        total_issues = sum(len(r["output"]["issues"]) for r in successful)
        token_usage: dict[str,int] = {}
        latency = 0.0
        effective_thinking = {}
        usage_rows = rows[:]
        global_validation = checkpoints.metadata("fewshot_validation")
        if global_validation:
            usage_rows.append({"audit":{"api_calls":{"generator":global_validation.get("api_calls",[])}}})
        for r in usage_rows:
            for role,calls in r["audit"].get("api_calls",{}).items():
                for call in calls:
                    if "effective_thinking" in call:
                        effective_thinking[role] = {**call["effective_thinking"],"actual_parameters":call.get("actual_thinking_parameters",{})}
            # HTTP clients also record usage for a truncated/otherwise rejected
            # response. Include it even though BaseAgent never received Completion.
            roles = set(r["audit"].get("requests",{})) | set(r["audit"].get("api_calls",{}))
            for role in roles:
                api_calls = r["audit"].get("api_calls",{}).get(role,[])
                requests = [c for c in api_calls if "usage" in c]
                if not requests:
                    requests = r["audit"].get("requests",{}).get(role,[])
                for request in requests:
                    latency += request.get("latency_seconds",0)
                    for k,v in request.get("usage",{}).items():
                        if type(v) is int:
                            token_usage[k] = token_usage.get(k,0)+v
        summary = {**preflight, "completed": count,"accepted":count,"rejected":rejected_count,
            "fewshot_grounding":"PASS" if global_validation else "NOT_APPROVED", "global_error":self.global_error,
            "failed": sum(r["status"]=="FAILED" for r in rows), "needs_review": sum(bool(r["audit"].get("needs_review")) for r in rows),
            "pending": sum(r["status"] in ["PENDING","RUNNING"] for r in rows), "output_records": exported,
            "run_complete": count+rejected_count == preflight["selected_records"], "total_issues": total_issues,
            "mean_issues_per_case": total_issues/count if count else 0,
            "mean_debate_rounds": sum(r["audit"].get("rounds",0) for r in terminal)/len(terminal) if terminal else 0,
            "early_stops": sum(bool(r["audit"].get("early_stop")) for r in rows),
            "pass_count": sum(r["audit"].get("consensus")=="PASS" for r in rows),
            "max_rounds_unresolved": sum(r["audit"].get("stop_reason")=="MAX_ROUNDS" for r in rows),
            "generator_contests": sum(r["audit"].get("generator_contests",0) for r in rows),
            "judge_changes": sum(r["audit"].get("judge_changes",0) for r in rows),
            "token_usage": token_usage, "summed_request_latency_seconds": latency, "effective_thinking":effective_thinking,
            "manifest": manifest, "effective_config": self.config.public_dict(),
            "quality_note": "Candidate labels; Judge PASS rate is not human-verified legal accuracy."}
        atomic_text(self.config.audit_dir/"summary.json",json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
        return summary

    async def run(self) -> dict:
        preflight = self.preflight()
        manifest = create_manifest(self.config, preflight["input_sha256"])
        if manifest["fewshot_sha256"] != self.fewshot.sha256:
            raise ValueError("Few-shot changed during preflight; rerun using stable input")
        if self.config.dry_run:
            return {**preflight,"dry_run":True,"manifest":manifest}
        for directory in [self.config.audit_dir,self.config.log_dir,self.config.checkpoint_dir,self.config.output_path.parent,self.config.rejected_path.parent]:
            directory.mkdir(parents=True,exist_ok=True)
        with ExitStack() as stack:
            # Lock both exports and the checkpoint to prevent cross-run collisions.
            for path in [p.with_name(p.name+".lock") for p in [self.config.output_path,self.config.rejected_path]]+[self.config.checkpoint_dir/"run.lock"]:
                handle = stack.enter_context(path.open("a"))
                try:
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError("Another pipeline process owns output/rejected/checkpoint lock") from None
            existing_checkpoint = (self.config.checkpoint_dir/"state.sqlite3").exists()
            if not existing_checkpoint:
                for directory in [self.config.audit_dir,self.config.log_dir]:
                    if any(p.name != "pipeline.log" for p in directory.iterdir()):
                        raise ValueError("Audit/log directory already contains artifacts; use new directories for a new run")
            if any(p.exists() for p in [self.config.output_path,self.config.rejected_path]) and not existing_checkpoint and not self.config.overwrite_output:
                raise ValueError("Existing output has no matching checkpoint; choose new paths or OVERWRITE_OUTPUT=true")
            checkpoints = CheckpointManager(self.config.checkpoint_dir,manifest,self.config.resume)
            stack.callback(checkpoints.close)
            handler = logging.FileHandler(self.config.log_dir/"pipeline.log",encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
            handler.setLevel(self.config.log_level)
            logging.getLogger().addHandler(handler)
            stack.callback(handler.close)
            stack.callback(logging.getLogger().removeHandler,handler)
            if not existing_checkpoint:
                from datetime import datetime,timezone
                for path in [self.config.output_path,self.config.rejected_path]:
                    if path.exists():
                        backup = path.with_name(path.name+".backup-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
                        path.rename(backup)
            reader = JSONLReader(self.config.input_path)
            for record in self._selected(reader):
                checkpoints.register(record.index,record.case_id)
            # Review all examples once using the existing Generator role. A
            # malformed/unsupported example aborts before reference examples are used.
            saved = checkpoints.metadata("fewshot_validation")
            if saved:
                self.fewshot.validate_report(FewShotValidation.model_validate_json(json.dumps(saved["report"])))
            else:
                validator = self._make_controller()
                try:
                    report = await validator.generator.validate_fewshot()
                    saved = {"report":report.model_dump(mode="json"),
                             "api_calls":getattr(validator.generator.client,"calls",[])}
                    checkpoints.set_metadata("fewshot_validation", saved)
                except Exception as exc:
                    self.global_error = "Few-shot approval failed: "+type(exc).__name__+": "+str(exc)
                    for agent in [self.config.gen,self.config.judge]:
                        key = agent.api_key.get_secret_value()
                        if key and key != "EMPTY":
                            self.global_error = self.global_error.replace(key,"<redacted>")
                    atomic_text(self.config.audit_dir/"fewshot_validation_failed.json",json.dumps({"error":self.global_error},ensure_ascii=False)+"\n")
                    self._export_audit(checkpoints,preflight,manifest,self._materialize(checkpoints))
                    raise
                finally:
                    await asyncio.gather(validator.generator.client.close(), validator.judge.client.close())
            atomic_text(self.config.audit_dir/"fewshot_validation.json",json.dumps(saved,ensure_ascii=False,indent=2)+"\n")
            # Rebuild a possibly interrupted output export before requesting inference.
            self._materialize(checkpoints)
            workers = asyncio.Semaphore(self.config.max_workers)
            batch = []
            try:
                for record in self._selected(reader):
                    if self.stop_requested.is_set():
                        break
                    batch.append(record)
                    if len(batch) >= self.config.batch_size:
                        await asyncio.gather(*(self._process(r,checkpoints,workers) for r in batch))
                        self._materialize(checkpoints)
                        batch.clear()
                if batch and not self.stop_requested.is_set():
                    await asyncio.gather(*(self._process(r,checkpoints,workers) for r in batch))
            finally:
                exported = self._materialize(checkpoints)
                summary = self._export_audit(checkpoints,preflight,manifest,exported)
            if reader.fingerprint() != preflight["input_sha256"]:
                raise ValueError("Input changed during run; reject this run and use stable input")
            if hashlib.sha256(self.config.fewshot_path.read_bytes()).hexdigest() != manifest["fewshot_sha256"]:
                raise ValueError("Few-shot changed during run; reject this run")
            # A filtered output is matched by checkpoint index, never by line offset.
            counts = ResultExporter(self.config).validate(checkpoints.records(),require_finished=False)
            if counts["records"] != exported or counts["rejected"] != summary["rejected"]:
                raise ValueError("Export record count mismatch")
            return summary
