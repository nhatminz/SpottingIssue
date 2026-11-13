"""Facts-only acceptance consistency; semantic correctness remains an LLM assessment."""
from __future__ import annotations
from ..schemas import JudgeOutput

RUBRIC_CRITERIA = ("grounding", "legal_relevance", "coverage", "independence", "format",
                   "explanation_quality", "consistency", "deduplication")


def scope_rubric_passes(judgment: JudgeOutput | dict) -> bool:
    data = judgment.model_dump(mode="json") if isinstance(judgment, JudgeOutput) else judgment
    if data.get("overall_verdict") != "PASS" or any(data.get("rubric", {}).get(key) != "PASS" for key in RUBRIC_CRITERIA):
        return False
    if any(data.get(key) for key in ("error_codes", "generator_visible_feedback", "unresolved_disputes")):
        return False
    if any(key not in data for key in ("per_issue_reviews", "coverage_analysis", "blind_comparison")):
        return False
    # Old full-judgment judgments cannot stand in for this contract.
    if "situation_audit" in data or any("court_scope_confirmed" in r or "markdown_evidence_quotes" in r for r in data["per_issue_reviews"]):
        return False
    reviews = data["per_issue_reviews"]
    ids = {r.get("issue_id") for r in reviews}
    if len(ids) != len(reviews):
        return False
    for r in reviews:
        if r.get("classification") != "CORE" or r.get("verdict") != "PASS" or r.get("error_codes") or not r.get("facts_evidence_quotes"):
            return False
    covered = set()
    for item in data["coverage_analysis"]:
        matches = set(item.get("matched_issue_ids", []))
        if not matches or not matches <= ids or not item.get("facts_evidence_quotes"):
            return False
        covered |= matches
    if covered != ids:
        return False
    return not any(c.get("disposition") not in ("MATCHED", "EXCLUDED") for c in data["blind_comparison"])
