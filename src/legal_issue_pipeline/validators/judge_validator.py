"""Conservative acceptance of semantic reviews, separate from JSON/schema repair.

Semantic contradictions are audit findings: they never throw a parsing exception,
never change a model's legal assessment, and can never be exported as PASS.
"""
from __future__ import annotations
import json
from typing import get_args
from pydantic import ValidationError
from ..schemas import JudgeOutput, IssueCriterion

RUBRIC_CRITERIA = ("grounding", "legal_relevance", "coverage", "independence", "format",
                   "explanation_quality", "consistency", "deduplication")
ISSUE_CRITERIA = get_args(IssueCriterion)
CRITERION_RUBRICS = {
    **{path: ("grounding",) for path in ISSUE_CRITERIA if path.startswith("factual_grounding.")},
    "subject_liability.subject_precision": ("consistency",),
    "subject_liability.conduct_attribution": ("grounding", "consistency"),
    "subject_liability.liability_precision": ("legal_relevance",),
    "subject_liability.subject_grouping": ("independence",),
    "atomicity.atomicity": ("independence",),
    "atomicity.independence": ("independence",),
    "atomicity.overlap": ("deduplication",),
    "atomicity.granularity": ("independence",),
    "explanation_review.factual_basis": ("grounding", "explanation_quality"),
    "explanation_review.legal_connection": ("explanation_quality",),
    "explanation_review.issue_alignment": ("explanation_quality", "consistency"),
}
CROSS_RUBRICS = {"coverage": "coverage", "deduplication": "deduplication",
                 "fragmentation": "independence", "over_merging": "independence"}
CROSS_KINDS = {"DUPLICATE": "deduplication", "FRAGMENTATION": "fragmentation", "OVER_MERGING": "over_merging"}


def atomic_reviews(review):
    """Yield all 16 required criteria with stable feedback paths."""
    for path in ISSUE_CRITERIA:
        group, key = path.split(".")
        yield path, getattr(getattr(review, group), key)


def consistency_errors(judgment: JudgeOutput) -> list[str]:
    """Validate semantic/status agreement without requesting JSON repair.

    Shape/IDs are checked by JudgeAgent. Exporter also invokes the same structural
    check, so a cached or manually edited checkpoint cannot bypass it.
    """
    errors = []
    feedback = judgment.generator_visible_feedback
    core_ids = {r.issue_id for r in judgment.per_issue_reviews if r.classification == 'CORE'}
    def require(condition, message):
        if not condition:
            errors.append(message)
    def rubric_adverse(name, status):
        expected = "FAIL" if status == "FAIL" else "NEEDS_REVIEW"
        # A different definite failure may also make this global rubric FAIL.
        require(getattr(judgment.rubric, name) in ({"FAIL"} if status == "FAIL" else {"FAIL", expected}),
                f"Rubric {name} contradicts {status}")
    for review in judgment.per_issue_reviews:
        criteria = list(atomic_reviews(review))
        statuses = [item.status for _, item in criteria]
        for path, criterion in criteria:
            if path.startswith("factual_grounding."):
                allowed = {"PASS": {"FACT", "SUPPORTED_INFERENCE"}, "FAIL": {"UNSUPPORTED"}, "UNCERTAIN": {"UNCERTAIN"}}
                require(criterion.basis in allowed[criterion.status], f"{review.issue_id}:{path}: basis/status conflict")
            if criterion.status != "PASS":
                linked = [f for f in feedback if
                    (review.issue_id in f.issue_ids and f.failed_criterion == path) or
                    any(ref.issue_id == review.issue_id and ref.criterion == path for ref in f.criterion_refs)]
                require(bool(linked), f"{review.issue_id}:{path}: no linked structured feedback")
                require(any(f.error_code in review.error_codes for f in linked),
                        f"{review.issue_id}:{path}: feedback/error code conflict")
                for rubric in CRITERION_RUBRICS[path]:
                    rubric_adverse(rubric, criterion.status)
        require(review.issue_supported == all(c.status == "PASS" for p,c in criteria if p.startswith('factual_grounding.')),
                f"{review.issue_id}: issue_supported conflicts with grounding criteria")
        require(review.explain_supported == all(c.status == "PASS" for p,c in criteria if p.startswith('explanation_review.')),
                f"{review.issue_id}: explain_supported conflicts with explanation criteria")
        if "FAIL" in statuses:
            require(review.verdict in {"REVISE", "REMOVE"}, f"{review.issue_id}: FAIL cannot have {review.verdict} verdict")
        elif "UNCERTAIN" in statuses:
            require(review.verdict == "NEEDS_REVIEW", f"{review.issue_id}: UNCERTAIN requires NEEDS_REVIEW")
        if review.verdict == "PASS":
            require(review.classification == "CORE" and not review.error_codes and all(s == "PASS" for s in statuses),
                    f"{review.issue_id}: PASS requires error-free CORE and all criteria PASS")
        else:
            require(bool(review.error_codes), f"{review.issue_id}: adverse review has no error code")
            require(any(review.issue_id in f.issue_ids for f in feedback), f"{review.issue_id}: adverse review has no feedback")
        require(set(review.error_codes) <= set(judgment.error_codes), f"{review.issue_id}: global error codes omit issue finding")
        if review.classification == "DUPLICATE":
            require(bool(set(review.related_issue_ids) & core_ids),
                    f"{review.issue_id}: duplicate must identify a covering CORE issue")
            require(any(f.error_code.value == "DUPLICATE" and review.issue_id in f.issue_ids for f in feedback),
                    f"{review.issue_id}: duplicate needs specific feedback")
    cross = judgment.cross_issue_evaluation
    for name, rubric in CROSS_RUBRICS.items():
        status = getattr(cross, name).status
        if status != "PASS":
            rubric_adverse(rubric, status)
    for finding in cross.findings:
        name = CROSS_KINDS[finding.kind]
        require(finding.kind == 'OVER_MERGING' or len(finding.issue_ids) >= 2,
                f"{finding.finding_id}: duplicate/fragmentation must identify the related issues")
        require(getattr(cross, name).status == "FAIL", f"{finding.finding_id}: finding contradicts cross-issue status")
        require(any(finding.finding_id in f.cross_issue_ids for f in feedback), f"{finding.finding_id}: no linked cross-issue feedback")
    for name in ("deduplication", "fragmentation", "over_merging"):
        if getattr(cross, name).status == "FAIL":
            require(any(CROSS_KINDS[f.kind] == name for f in cross.findings), f"Cross {name}: FAIL needs a finding")
        if getattr(cross, name).status == "UNCERTAIN":
            require(bool(judgment.unresolved_disputes) or bool(feedback), f"Cross {name}: uncertainty needs feedback/dispute")
    for item in judgment.coverage_analysis:
        tests = list(item.tests.model_dump().values())
        accepted_inventory = all(t['status'] == 'PASS' for t in tests)
        require(not any(t['status'] == 'FAIL' for t in tests), f"{item.coverage_id}: failed proposal must be excluded from CORE inventory")
        if not accepted_inventory:
            rubric_adverse('coverage', 'UNCERTAIN')
            require(cross.coverage.status != 'PASS', f"{item.coverage_id}: uncertain coverage cannot PASS")
        if not item.matched_issue_ids:
            require(cross.coverage.status != 'PASS' and judgment.rubric.coverage != 'PASS', f"{item.coverage_id}: uncovered question cannot PASS")
            adds = [f for f in feedback if item.coverage_id in f.coverage_ids and f.action == 'ADD'
                    and f.failed_criterion == 'COVERAGE' and f.error_code.value == 'MISSING_CORE_ISSUE' and not f.issue_ids]
            if accepted_inventory:
                require(bool(adds), f"{item.coverage_id}: missing independent CORE needs linked ADD feedback")
                require(cross.coverage.status == 'FAIL' and judgment.rubric.coverage == 'FAIL', f"{item.coverage_id}: missing CORE requires coverage FAIL")
            else:
                require(not adds, f"{item.coverage_id}: ADD requires all four coverage tests PASS")
        require(not any(f.action == 'ADD' and item.coverage_id in f.coverage_ids for f in feedback) or
                (accepted_inventory and not item.matched_issue_ids), f"{item.coverage_id}: invalid ADD")
    for f in feedback:
        require(f.error_code in judgment.error_codes, f"{f.feedback_id}: global error codes omit feedback finding")
        if f.action == 'ADD':
            require(not f.issue_ids and bool(f.coverage_ids) and f.failed_criterion == 'COVERAGE',
                    f"{f.feedback_id}: ADD requires uncovered coverage IDs and no current issue IDs")
        else:
            require(bool(f.issue_ids), f"{f.feedback_id}: non-ADD feedback requires current issue IDs")
    if any(c.disposition == 'NEEDS_REVIEW' for c in judgment.blind_comparison):
        require(cross.coverage.status != 'PASS' and judgment.rubric.coverage != 'PASS', 'Blind uncertainty cannot pass coverage')
    if judgment.overall_verdict == 'PASS':
        require(_all_pass(judgment), 'Overall PASS contradicts unresolved criteria, coverage, feedback or disputes')
    elif judgment.overall_verdict == 'NEEDS_REVIEW':
        require(not any(c.status == 'FAIL' for r in judgment.per_issue_reviews for _,c in atomic_reviews(r)),
                'Overall NEEDS_REVIEW cannot hide a definite criterion FAIL')
    if judgment.overall_verdict != 'PASS':
        require(bool(feedback or judgment.unresolved_disputes), 'Non-PASS needs feedback or an explicit unresolved dispute')
    return list(dict.fromkeys(errors))


def _all_pass(judgment: JudgeOutput) -> bool:
    if any(getattr(judgment.rubric, key) != 'PASS' for key in RUBRIC_CRITERIA):
        return False
    if judgment.error_codes or judgment.generator_visible_feedback or judgment.unresolved_disputes:
        return False
    if any(r.verdict != 'PASS' or r.classification != 'CORE' or r.error_codes or not r.issue_supported
           or not r.explain_supported or any(c.status != 'PASS' for _,c in atomic_reviews(r)) for r in judgment.per_issue_reviews):
        return False
    cross = judgment.cross_issue_evaluation
    if cross.findings or any(getattr(cross, name).status != 'PASS' for name in CROSS_RUBRICS):
        return False
    ids = {r.issue_id for r in judgment.per_issue_reviews}
    covered = set()
    for item in judgment.coverage_analysis:
        if not item.matched_issue_ids or not set(item.matched_issue_ids) <= ids or any(
                t['status'] != 'PASS' for t in item.tests.model_dump().values()):
            return False
        covered.update(item.matched_issue_ids)
    return covered == ids and all(c.disposition in {'MATCHED','EXCLUDED'} for c in judgment.blind_comparison)


def scope_rubric_passes(judgment: JudgeOutput | dict) -> bool:
    try:
        # Reparse model instances too: assignment/model_copy can bypass Pydantic.
        value = JudgeOutput.model_validate_json(json.dumps(judgment.model_dump(mode='json') if isinstance(judgment, JudgeOutput) else judgment))
        from ..agents.judge import validate_structure
        validate_structure(value)
        return value.overall_verdict == 'PASS' and not consistency_errors(value) and _all_pass(value)
    except (ValueError, ValidationError, TypeError, KeyError):
        return False
