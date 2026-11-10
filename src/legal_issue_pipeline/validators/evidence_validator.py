from __future__ import annotations


class EvidenceError(ValueError):
    pass


def validate_quotes(quotes: list[str], source: str, label: str, required: bool = True) -> None:
    if required and not quotes:
        raise EvidenceError(f"{label}: at least one exact quote required")
    for quote in quotes:
        if not quote.strip() or quote not in source:
            # Do not include untrusted/possibly private quotes in a repair instruction.
            raise EvidenceError(f"{label}: quote absent from the permitted source")
