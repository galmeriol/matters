"""Talking to language models without knowing which one.

Role: Provider
    complete_json(system, user, schema, max_tokens) -> Completion(data, usage)
One request in, one JSON object (matching the schema) out. Everything
provider-specific stays in its adapter: how to ask for JSON, how thinking and
effort are set, which errors mean what, and which credentials it needs.
Adapters raise ModelError with one sentence a person can act on.

Player: ClaudeCodeProvider (llm/claude_code.py), Claude through the local Claude Code
CLI, so nothing but Claude Code is needed. `from_env()` (llm/registry.py) sets it up
from MATTERS_MODEL / MATTERS_EFFORT.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

type Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORTS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True, slots=True)
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0  # thinking included

    def __add__(self, other: "Usage") -> "Usage":
        """Two requests' usage, under this one's model."""
        return Usage(
            self.model,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True, slots=True)
class Completion:
    data: dict[str, Any]
    usage: Usage


@runtime_checkable
class Provider(Protocol):
    """Role: one structured-output request to some model."""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def setup_hint(self) -> str:
        """How to give it credentials, for a page that can't call a model yet (HTML-safe text)."""
        ...

    def configured(self) -> bool:
        """Credentials are available (the request may still fail)."""
        ...

    def complete_json(
        self, system: str, user: str, schema: dict[str, Any], *, max_tokens: int
    ) -> Completion: ...
