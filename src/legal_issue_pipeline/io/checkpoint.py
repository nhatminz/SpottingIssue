"""SQLite is the durable source of truth; JSONL is an atomic ordered projection."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from ..config import digest
from .jsonl_writer import atomic_text


class CheckpointManager:
    def __init__(self, directory: Path, manifest: dict, resume: bool):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/"state.sqlite3"
        if path.exists() and not resume:
            raise ValueError("Checkpoint already exists; use RESUME=true or a new checkpoint directory")
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records (idx INTEGER PRIMARY KEY, case_id TEXT UNIQUE NOT NULL,
              status TEXT NOT NULL, output TEXT, audit TEXT, error TEXT, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,
              idx INTEGER, status TEXT, timestamp TEXT NOT NULL);
        """)
        existing = self.db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
        if existing and json.loads(existing[0]) != manifest:
            self.db.close()
            raise ValueError("Resume fingerprint mismatch (input/config/prompts/code); use NEW output/audit/checkpoint paths")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('manifest',?)", (json.dumps(manifest, sort_keys=True),))
        atomic_text(directory/"manifest.json", json.dumps({**manifest,"manifest_hash":digest(manifest)},ensure_ascii=False,indent=2)+"\n")

    def register(self, index: int, case_id: str):
        if not self.get(index):
            self.set(index, case_id, "PENDING")

    def metadata(self, key: str):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_metadata(self, key: str, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def get(self, index: int) -> dict | None:
        row = self.db.execute("SELECT idx,case_id,status,output,audit,error FROM records WHERE idx=?", (index,)).fetchone()
        if not row:
            return None
        return self._decode_row(row)

    @staticmethod
    def _decode_row(row) -> dict:
        return {"index": row[0], "case_id": row[1], "status": row[2], "output": json.loads(row[3]) if row[3] else None,
                "audit": json.loads(row[4]) if row[4] else {}, "error": row[5]}

    @classmethod
    def read_records(cls, directory: Path, manifest: dict) -> list[dict]:
        path = directory/"state.sqlite3"
        if not path.is_file():
            raise ValueError("Matching checkpoint required to validate filtered PASS-only output")
        db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
        try:
            stored = db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
            if not stored or json.loads(stored[0]) != manifest:
                raise ValueError("Resume fingerprint mismatch (input/config/prompts/code); use NEW output/audit/checkpoint paths")
            return [cls._decode_row(row) for row in db.execute("SELECT idx,case_id,status,output,audit,error FROM records ORDER BY idx")]
        finally:
            db.close()

    def set(self, index: int, case_id: str, status: str, output=None, audit=None, error=None):
        now = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?) ON CONFLICT(idx) DO UPDATE SET status=excluded.status,output=excluded.output,audit=excluded.audit,error=excluded.error,updated=excluded.updated",
                            (index,case_id,status,json.dumps(output,ensure_ascii=False) if output is not None else None,
                             json.dumps(audit,ensure_ascii=False) if audit is not None else None,error,now))
            self.db.execute("INSERT INTO events(idx,status,timestamp) VALUES (?,?,?)",(index,status,now))

    def records(self) -> list[dict]:
        return [self.get(r[0]) for r in self.db.execute("SELECT idx FROM records ORDER BY idx").fetchall()]

    def events(self) -> list[dict]:
        return [dict(index=r[0],status=r[1],timestamp=r[2]) for r in self.db.execute("SELECT idx,status,timestamp FROM events ORDER BY id")]

    def close(self):
        self.db.close()
