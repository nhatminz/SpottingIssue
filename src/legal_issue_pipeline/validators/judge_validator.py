"""Consistency of the Judge's scope claims, not a regex substitute for legal judgment."""
from __future__ import annotations

from ..schemas import JudgeOutput

RUBRIC_CRITERIA = ("legal_relevance", "coverage", "grounding", "format")


def scope_rubric_passes(judgment: JudgeOutput | dict) -> bool:
    """Shared acceptance gate for live debate and checkpoint export.

    Source quotations and reference integrity are checked by JudgeAgent. Semantic
    relevance, equivalence and scope remain the Judge's explicit, auditable claims.
    Missing new fields fail closed, including for historical PASS records.
    """
    data = judgment.model_dump(mode="json") if isinstance(judgment,JudgeOutput) else judgment
    rubric = data.get("rubric",{})
    if any(rubric.get(key) != "PASS" for key in RUBRIC_CRITERIA):
        return False
    if any(key not in data for key in ["per_issue_reviews","coverage_analysis","blind_comparison"]):
        return False
    reviews = data["per_issue_reviews"]
    ids = {review.get("issue_id") for review in reviews}
    if len(ids) != len(reviews):
        return False
    for review in reviews:
        if (review.get("classification") != "CORE" or review.get("court_scope_confirmed") is not True
            or not review.get("situation_evidence_quotes") or not review.get("markdown_evidence_quotes")
            or review.get("verdict") != "PASS" or review.get("error_codes")):
            return False
    covered = set()
    for item in data["coverage_analysis"]:
        matched = set(item.get("matched_issue_ids",[]))
        if (not matched or not matched <= ids or item.get("court_scope_confirmed") is not True
            or not item.get("situation_evidence_quotes") or not item.get("markdown_evidence_quotes")):
            return False
        covered |= matched
    if covered != ids:
        return False
    return not any(c.get("disposition") not in ["MATCHED","EXCLUDED"] for c in data["blind_comparison"])
