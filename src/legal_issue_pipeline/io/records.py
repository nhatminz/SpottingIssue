"""Input validation and an explicit allowlist for the Generator's full sources."""
from __future__ import annotations

REQUIRED_SEED_FIELDS = ("facts_clean", "facts", "application", "conclusion")


def validate_record(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("Record must be an object")
    for key in ("doc_name", "markdown"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Missing or invalid {key}")
    conflict = {"issues", "explain"} & data.keys()
    if conflict:
        raise ValueError(f"Input output-field conflict: {sorted(conflict)}; existing labels are never overwritten")
    seed = data.get("benchmark_seed")
    if not isinstance(seed, dict):
        raise ValueError("Missing or invalid benchmark_seed")
    for key in REQUIRED_SEED_FIELDS:
        if not isinstance(seed.get(key), str) or not seed[key].strip():
            raise ValueError(f"Missing or invalid benchmark_seed.{key}; no fallback allowed")


def generator_sources(record: dict) -> dict:
    validate_record(record)
    return {"benchmark_seed": {key: record["benchmark_seed"][key] for key in REQUIRED_SEED_FIELDS},
            "markdown": record["markdown"]}
