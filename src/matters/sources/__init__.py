"""Sources find one tool's local session files, read them and normalise them."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from matters.session import Session


@runtime_checkable
class Source(Protocol):
    """Role: everything one tool recorded, as Sessions. Read-only.

    With a project, only that project's sessions; without, all of them.
    """

    def sessions(self, project: Path | None = None) -> list[Session]: ...


def all_sources() -> list[Source]:
    from matters.sources.claude_code import ClaudeCode

    return [ClaudeCode()]
