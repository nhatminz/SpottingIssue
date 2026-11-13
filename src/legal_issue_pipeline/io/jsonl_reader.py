from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from ..agents.base_agent import reject_duplicate_keys
from .records import validate_record


@dataclass
class InputRecord:
    index: int
    case_id: str
    data: dict


class JSONLReader:
    def __init__(self, path: Path):
        self.path = path

    def __iter__(self):
        with self.path.open(encoding="utf-8") as source:
            for index,line in enumerate(source):
                try:
                    data = json.loads(line, object_pairs_hook=reject_duplicate_keys,
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
                    validate_record(data)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Input line {index+1}: {exc}") from None
                stable = hashlib.sha256(f"{index}:{data['doc_name']}".encode()).hexdigest()[:16]
                yield InputRecord(index, f"{index:08d}-{stable}", data)

    def fingerprint(self) -> str:
        result = hashlib.sha256()
        with self.path.open("rb") as source:
            for block in iter(lambda: source.read(1024*1024), b""):
                result.update(block)
        return result.hexdigest()
