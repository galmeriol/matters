"""What happened to one file, as a stack of changes: every edit the assistant made to it,
in the order it made them, each traceable to its turn.

From the record only. An Edit records the snippet it replaced, not the whole file, so the
changes can't be folded into one net diff; the stack is the honest shape. Failed edits
changed nothing: they are counted, not stacked. Nothing is read from disk or git, which
would show the file as it is now rather than as the session left it.
"""

import difflib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

from matters.session import Entry, Session

type How = Literal["edit", "write"]


@dataclass(frozen=True, slots=True)
class Hunk:
    old: str
    new: str

    @property
    def lines(self) -> tuple[int, int]:
        """Lines added and removed."""
        old, new = self.old.splitlines(), self.new.splitlines()
        added = removed = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1
        return added, removed


@dataclass(frozen=True, slots=True)
class Change:
    """One layer of the stack: one tool call that changed the file."""

    session: Session
    turn: int  # 1-based, as on the page
    entry: Entry
    how: How
    hunks: tuple[Hunk, ...]

    @classmethod
    def from_step(cls, session: Session, turn: int, step: Entry) -> "Change | None":
        """What an edit call changed, as hunks; None for a step that edited nothing."""
        if step.tool is None:
            return None
        given = step.tool.input
        match step.tool.name:
            case "Write":
                return cls(session, turn, step, "write", (Hunk("", str(given.get("content", ""))),))
            case "MultiEdit":
                edits = [e for e in given.get("edits") or [] if isinstance(e, dict)]
                hunks = tuple(_hunk(e) for e in edits)
                return cls(session, turn, step, "edit", hunks) if hunks else None
            case "Edit":
                return cls(session, turn, step, "edit", (_hunk(given),))
            case _:  # NotebookEdit and the like: say it happened, without a diff
                return cls(session, turn, step, "edit", ())

    @classmethod
    def all_in(cls, session: Session, path: str | None = None) -> Iterator["Change"]:
        """Every change that took in a session, to one file or to any."""
        for turn in session.turns:
            for step in turn.steps:
                touched = step.changed and path in (None, step.changed[0])
                if touched and (change := cls.from_step(session, turn.number, step)):
                    yield change

    @staticmethod
    def totals(changes: Iterable["Change"]) -> tuple[int, int]:
        """Lines added and removed, all told."""
        counts = [(c.added, c.removed) for c in changes]
        return sum(a for a, _ in counts), sum(r for _, r in counts)

    @property
    def added(self) -> int:
        return sum(h.lines[0] for h in self.hunks)

    @property
    def removed(self) -> int:
        return sum(h.lines[1] for h in self.hunks)


@dataclass(frozen=True, slots=True)
class Stack:
    path: str
    changes: tuple[Change, ...]  # oldest first: the bottom of the stack
    failed: int = 0  # edits that failed and changed nothing

    @classmethod
    def of(cls, sessions: Sequence[Session], path: str) -> "Stack":
        """Every change to `path` in these sessions, oldest session first."""
        ordered = sorted(sessions, key=lambda s: s.started_at or "")
        changes = tuple(c for session in ordered for c in Change.all_in(session, path))
        failed = sum(1 for s in ordered for e in s.entries if e.failed and path in e.files)
        return cls(path, changes, failed)

    @property
    def added(self) -> int:
        return sum(c.added for c in self.changes)

    @property
    def removed(self) -> int:
        return sum(c.removed for c in self.changes)

    @property
    def sessions(self) -> tuple[Session, ...]:
        return tuple({c.session.id: c.session for c in self.changes}.values())


def _hunk(edit: dict[str, object]) -> Hunk:
    return Hunk(str(edit.get("old_string", "")), str(edit.get("new_string", "")))
