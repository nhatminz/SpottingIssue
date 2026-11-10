from __future__ import annotations
from copy import deepcopy


def make_output(original: dict, issues: list[str], situation_error: bool) -> dict:
    output = deepcopy(original)
    output.update(issues=issues, situation_error=situation_error)
    validate_output(original, output)
    return output


def validate_output(original: dict, output: dict) -> None:
    if set(output) != set(original) | {"issues", "situation_error"}:
        raise ValueError("Output keys do not match original plus the two permitted fields")
    for key,value in original.items():
        if key not in {"issues", "situation_error"} and output.get(key) != value:
            raise ValueError(f"Original field changed: {key}")
    if type(output.get("situation_error")) is not bool:
        raise ValueError("situation_error must be boolean")
    if not isinstance(output.get("issues"), list) or any(not isinstance(i,str) or not i.strip() for i in output["issues"]):
        raise ValueError("issues must be a list of nonempty strings")
