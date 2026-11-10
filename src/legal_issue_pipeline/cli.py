from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from pydantic import ValidationError
from .config import load_config
from .io.checkpoint import CheckpointManager
from .io.result_exporter import ResultExporter
from .pipeline.runner import PipelineRunner, create_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Vietnamese legal issue candidate pipeline (configuration via environment)")
    parser.add_argument("command",choices=["run","inspect","validate"],nargs="?",default="run")
    args = parser.parse_args()
    try:
        config = load_config()
        logging.basicConfig(level=config.log_level,format="%(asctime)s %(levelname)s %(name)s %(message)s")
        if args.command == "validate":
            preflight = PipelineRunner(config).preflight()
            manifest = create_manifest(config,preflight["input_sha256"])
            rows = CheckpointManager.read_records(config.checkpoint_dir,manifest)
            print(json.dumps(ResultExporter(config).validate(rows),ensure_ascii=False))
            return 0
        print(json.dumps({"effective_config":config.public_dict()},ensure_ascii=False,indent=2))
        runner = PipelineRunner(config)
        summary = runner.preflight() if args.command == "inspect" else asyncio.run(runner.run())
        print(json.dumps(summary,ensure_ascii=False,indent=2))
        if args.command == "run" and not config.dry_run:
            return 0 if summary["run_complete"] and not summary["failed"] else 2
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Resume with identical semantic configuration.",file=sys.stderr)
        return 130
    except ValidationError as exc:
        # Pydantic's default string includes input_value, possibly an API key.
        print("ERROR configuration: "+json.dumps([{"loc":list(e["loc"]),"type":e["type"],"message":e["msg"]} for e in exc.errors()],ensure_ascii=False),file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
