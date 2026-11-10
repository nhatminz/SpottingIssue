from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    """A request failed without creating a usable candidate."""


class ContextLimitError(LLMError):
    pass


@dataclass
class Completion:
    content: str
    usage: dict = field(default_factory=dict)
    latency_seconds: float = 0
    request_id: str = ""


class LLMClient(Protocol):
    async def complete(self, messages: list[dict], schema: dict) -> Completion: ...
    async def close(self) -> None: ...
