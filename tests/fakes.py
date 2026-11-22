"""Fakes that play the roles, so tests can isolate one object from the rest.

test_roles.py checks them against the same Protocols as the real players.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from matters.errors import ModelError
from matters.knowledge.extractor import Extracted
from matters.knowledge.model import Draft, Item
from matters.llm import Completion, Usage
from matters.session import Session
from matters.transcript import Transcript

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSource:
    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions

    def sessions(self, project: Path | None = None) -> list[Session]:
        return self._sessions


class FakeProvider:
    """A model that answers with whatever it was given, or fails with the given error."""

    name = "fake"
    setup_hint = "Install the fake model"

    def __init__(
        self,
        answer: dict[str, Any] | None = None,
        error: ModelError | None = None,
        *,
        configured: bool = True,
        then: Sequence[dict[str, Any] | ModelError] = (),
    ) -> None:
        """`then`: what later requests get, in order, after the first; past its end,
        requests get `answer` again."""
        self.answer = answer or {}
        self.then = list(then)
        self.error = error
        self._configured = configured
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def model(self) -> str:
        return "fake-model"

    def configured(self) -> bool:
        return self._configured

    def complete_json(
        self, system: str, user: str, schema: dict[str, Any], *, max_tokens: int
    ) -> Completion:
        self.requests.append((system, user, schema))
        if self.error:
            raise self.error
        later = len(self.requests) - 2
        reply = self.then[later] if 0 <= later < len(self.then) else self.answer
        if isinstance(reply, ModelError):
            raise reply
        return Completion(reply, Usage(self.model, 10, 5))


class FakeExtractor:
    """Proposes the given drafts, whatever it reads."""

    model = "fake-model"

    def __init__(self, drafts: tuple[Draft, ...] = ()) -> None:
        self.drafts = drafts

    def extract(
        self, transcript: Transcript, known: Sequence[Item], projects: Mapping[str, str]
    ) -> Extracted:
        return Extracted(self.drafts, Usage(self.model, 1, 1))
