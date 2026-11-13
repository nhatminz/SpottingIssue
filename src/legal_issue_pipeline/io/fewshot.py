"""Strict normalization. No application/conclusion/markdown enters examples."""
from __future__ import annotations
import hashlib
import json
import logging
from copy import deepcopy
from pathlib import Path
from ..agents.base_agent import reject_duplicate_keys
from ..validators.evidence_validator import validate_quotes
from ..schemas import FewShotValidation

log = logging.getLogger(__name__)
CATEGORIES = {"Marriage & Family", "Criminal", "Civil", "Commercial", "Administrative"}


class FewShotBank:
    def __init__(self, path: Path):
        self.path = path
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.examples = []
        self.identities = []
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line, object_pairs_hook=reject_duplicate_keys,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
                if not isinstance(row, dict):
                    raise ValueError("example must be an object")
                facts = row.get("benchmark_seed", {}).get("facts_clean")
                if not isinstance(facts, str) or not facts.strip():
                    raise ValueError("missing benchmark_seed.facts_clean")
                labels = row.get("issues")
                if not isinstance(labels, list) or not labels:
                    raise ValueError("issues must be a nonempty list")
                if all(isinstance(x, dict) for x in labels):
                    issues = [x.get("issue") for x in labels]
                    explains = [x.get("explain") for x in labels]
                elif all(isinstance(x, str) for x in labels):
                    issues, explains = labels, row.get("explain")
                else:
                    raise ValueError("mixed/invalid few-shot issue representation")
                if not isinstance(explains, list) or len(issues) != len(explains):
                    raise ValueError("unmatched issues/explain")
                if any(not isinstance(x, str) or len(x.strip()) < 20 for x in issues + explains):
                    raise ValueError("empty or generic issue/explain")
                category = row.get("category")
                if category not in CATEGORIES:
                    raise ValueError("unknown few-shot category")
                for text in issues + explains:
                    if any(marker in text.casefold() for marker in ("theo application", "theo conclusion", "tòa án nhận định", "tòa đã tuyên")):
                        raise ValueError("few-shot issue/explain references judicial analysis/outcome")
                self.examples.append({"example_id": f"E{index+1}", "category": category,
                                      "facts_clean": facts, "issues": issues, "explain": explains})
                self.identities.append({key: row.get(key) for key in ("doc_name", "official_document_id", "web_url")})
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"Few-shot line {index+1}: {exc}") from None
        if len(self.examples) != 5 or {x["category"] for x in self.examples} != CATEGORIES:
            raise ValueError("Few-shot must contain exactly five examples, one for each required category")

    def for_record(self, record: dict) -> tuple[list[dict], list[str]]:
        selected, excluded = [], []
        facts = record["benchmark_seed"]["facts_clean"]
        normalized = " ".join(facts.split())
        for example, identity in zip(self.examples, self.identities):
            same = normalized == " ".join(example["facts_clean"].split())
            same |= any(identity[key] and identity[key] == record.get(key) for key in identity)
            if same:
                excluded.append(example["example_id"])
            else:
                selected.append(deepcopy(example))
        return selected, excluded

    def validate_report(self, report: FewShotValidation) -> None:
        expected = {(x["example_id"], index) for x in self.examples for index in range(len(x["issues"]))}
        actual = [(x.example_id, x.issue_index) for x in report.checks]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("Few-shot grounding check must review every issue/explain pair exactly once")
        by_id = {x["example_id"]: x for x in self.examples}
        for check in report.checks:
            validate_quotes(check.facts_evidence_quotes, by_id[check.example_id]["facts_clean"], "few-shot facts")
            if not check.issue_supported or not check.explain_supported:
                raise ValueError(f"Unsupported few-shot {check.example_id} issue {check.issue_index}: {check.explanation}")
