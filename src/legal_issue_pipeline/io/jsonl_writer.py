from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


def atomic_text(path: Path, text: str) -> None:
    atomic_lines(path, [text])


def atomic_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,name = tempfile.mkstemp(prefix="."+path.name+".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            for line in lines:
                output.write(line)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class JSONLWriter:
    def __init__(self, path: Path):
        self.path = path

    def write(self, records: Iterable[dict]) -> None:
        atomic_lines(self.path, (json.dumps(r, ensure_ascii=False, allow_nan=False)+"\n" for r in records))
