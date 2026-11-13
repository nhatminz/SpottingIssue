"""Strict normalization. No application/conclusion/markdown enters examples."""
from __future__ import annotations
import hashlib
import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from ..agents.base_agent import reject_duplicate_keys
from ..validators.evidence_validator import validate_quotes
from ..schemas import FewShotValidation, FewShotReview
from ..llm.base_client import LLMError

log = logging.getLogger(__name__)
CATEGORIES = {"Marriage & Family", "Criminal", "Civil", "Commercial", "Administrative"}


class FewShotGroundingError(LLMError):
    """A valid review found unsupported reference content; JSON repair cannot fix it."""
    def __init__(self, report: FewShotReview, findings: list[dict]):
        self.report = report.model_dump(mode="json")
        self.findings = findings
        details = "\n".join(f"{x['example_id']} doc_name={x['doc_name']} issue_index={x['issue_index']} "
                            f"(issue #{x['issue_index']+1}): {x['explanation']}" for x in findings)
        super().__init__("Unsupported few-shot reference content; edit the reference issue/explain, not the facts.\n"+details)


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
        self.fact_spans = {
            example["example_id"]: [
                {"span_id": f"{example['example_id']}-S{index+1}", "text": text}
                for index, text in enumerate(match.group() for match in re.finditer(r"[^\r\n]+", example["facts_clean"])
                                             if match.group().strip())]
            for example in self.examples}

    def validation_examples(self) -> list[dict]:
        return [{**deepcopy(example), "facts_spans": deepcopy(self.fact_spans[example["example_id"]])}
                for example in self.examples]

    def resolve_review(self, review: FewShotReview) -> FewShotValidation:
        expected = {(x["example_id"], index) for x in self.examples for index in range(len(x["issues"]))}
        actual = [(x.example_id, x.issue_index) for x in review.checks]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("Few-shot review must cover every example/issue_index pair exactly once")
        identities = {example["example_id"]: identity for example, identity in zip(self.examples, self.identities)}
        by_id = {example["example_id"]: example for example in self.examples}
        findings = [{**check.model_dump(mode="json"), "doc_name": identities[check.example_id]["doc_name"],
                     "issue": by_id[check.example_id]["issues"][check.issue_index],
                     "explain": by_id[check.example_id]["explain"][check.issue_index]}
                    for check in review.checks if not check.issue_supported or not check.explain_supported]
        # A semantic rejection is already actionable. Do not let citation/JSON
        # repair hide it or pressure a later response to flip a false flag.
        if findings:
            raise FewShotGroundingError(review, findings)
        checks = []
        for check in review.checks:
            source = {span["span_id"]: span["text"] for span in self.fact_spans[check.example_id]}
            if (not check.facts_span_ids or len(check.facts_span_ids) != len(set(check.facts_span_ids))
                    or set(check.facts_span_ids)-source.keys()):
                raise ValueError(f"Unknown or duplicate facts_span_ids for {check.example_id} issue_index={check.issue_index}; "
                                 "select only span_id values supplied for this example")
            checks.append({**check.model_dump(exclude={"facts_span_ids"}),
                           "facts_evidence_quotes": [source[key] for key in check.facts_span_ids]})
        report = FewShotValidation.model_validate_json(json.dumps({"checks": checks}, ensure_ascii=False))
        self.validate_report(report)
        return report

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
