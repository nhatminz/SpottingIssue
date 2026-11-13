from __future__ import annotations
from copy import deepcopy


def make_output(original: dict, issues: list[str], explain: list[str]) -> dict:
    if {"issues", "explain"} & original.keys():
        raise ValueError("Input output-field conflict: issues/explain must not already exist")
    output = deepcopy(original)
    output.update(issues=list(issues), explain=list(explain))
    validate_output(original, output)
    return output


def validate_output(original: dict, output: dict) -> None:
    if {"issues", "explain"} & original.keys():
        raise ValueError("Input already contains issues/explain")
    if set(output) != set(original) | {"issues", "explain"}:
        raise ValueError("Output must add exactly issues and explain")
    for key, value in original.items():
        if key not in output or output[key] != value:
            raise ValueError(f"Original field changed: {key}")
    for key in ("issues", "explain"):
        if not isinstance(output.get(key), list) or any(not isinstance(x, str) or not x.strip() for x in output[key]):
            raise ValueError(f"{key} must be a list of nonempty strings")
    if len(output["issues"]) != len(output["explain"]):
        raise ValueError("issues/explain lengths differ")
