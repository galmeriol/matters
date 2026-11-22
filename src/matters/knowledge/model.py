"""What a knowledge item is: one preference or fact, scoped, categorised, and traceable to
the human's own words in a session."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Any, Literal

type Kind = Literal["preference", "fact"]
type Status = Literal["candidate", "accepted", "rejected"]
type Relation = Literal["new", "duplicate", "updates", "contradicts"]

KINDS: tuple[Kind, ...] = ("preference", "fact")
STATUSES: tuple[Status, ...] = ("candidate", "accepted", "rejected")
# The order of sections in PREFERENCES.md / FACTS.md, and of groups on the page.
CATEGORIES = (
    "architecture", "design", "code style", "tech", "wording", "workflow", "domain",
    "environment",
)  # fmt: skip
CATEGORY_HELP = {
    "architecture": "system shape, boundaries, roles, data flow",
    "design": "user experience, visual style, interaction",
    "code style": "naming, structure, idioms, tests, comments",
    "tech": "languages, libraries, tools, services and their versions",
    "wording": "tone and words in docs, UI text, messages",
    "workflow": "how to work together: process, checks, git, asking vs acting",
    "domain": "the subject the project is about",
    "environment": "machines, accounts, setups and their quirks",
}
RELATIONS: tuple[Relation, ...] = ("new", "duplicate", "updates", "contradicts")
GLOBAL = "global"  # the scope of what holds everywhere; otherwise a project path


@dataclass(frozen=True, slots=True)
class Evidence:
    session_id: str
    turn: int
    quote: str  # the human's words, verbatim and short

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(str(data["session_id"]), int(data["turn"]), str(data["quote"]))

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "turn": self.turn, "quote": self.quote}

    @staticmethod
    def to_json(evidence: Sequence["Evidence"]) -> str:
        return json.dumps([e.to_dict() for e in evidence])

    @classmethod
    def from_json(cls, text: str) -> tuple["Evidence", ...]:
        return tuple(cls.from_dict(e) for e in json.loads(text))


@dataclass(frozen=True, slots=True)
class Draft:
    """What extraction proposes, before it is stored."""

    kind: Kind
    scope: str  # GLOBAL or a project path
    category: str
    statement: str
    why: str
    basis: Literal["stated", "reaction"]
    evidence: tuple[Evidence, ...]
    relation: Relation = "new"
    related_id: int | None = None  # the accepted item it duplicates, updates or contradicts

    def with_evidence_of(self, other: "Draft") -> "Draft":
        """This draft, also citing where the other was said. Said outright anywhere
        counts as stated."""
        seen = {(e.session_id, e.turn) for e in self.evidence}
        more = tuple(e for e in other.evidence if (e.session_id, e.turn) not in seen)
        stated = "stated" in (self.basis, other.basis)
        return replace(
            self, evidence=self.evidence + more, basis="stated" if stated else "reaction"
        )

    def merged_with(self, repeat: "Draft") -> "Draft":
        """A repeat folded in: its evidence, and its reason when this one had none."""
        return replace(self.with_evidence_of(repeat), why=self.why or repeat.why)


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    kind: Kind
    scope: str
    category: str
    statement: str
    why: str
    basis: str
    evidence: tuple[Evidence, ...]
    status: Status
    relation: Relation
    related_id: int | None
    model: str
    created_at: str
    decided_at: str = ""

    @classmethod
    def from_row(cls, row: Sequence[object]) -> "Item":
        """A row of the store's `knowledge` table, columns in its order. A value the
        types don't know reads as the safe default: a preference, a candidate, new."""
        (iid, kind, scope, category, statement, why, basis, evidence, status, relation, related,
         model, created, decided) = row  # fmt: skip
        return cls(
            id=int(str(iid)),
            kind=_one_of(kind, KINDS, "preference"),
            scope=str(scope),
            category=str(category),
            statement=str(statement),
            why=str(why),
            basis=str(basis),
            evidence=Evidence.from_json(str(evidence)),
            status=_one_of(status, STATUSES, "candidate"),
            relation=_one_of(relation, ("updates", "contradicts"), "new"),
            related_id=int(str(related)) if related is not None else None,
            model=str(model),
            created_at=str(created),
            decided_at=str(decided),
        )

    @property
    def sessions(self) -> int:
        return len({e.session_id for e in self.evidence})

    def turns_in(self, session_id: str) -> list[int]:
        """The turns of one session this item cites."""
        return sorted({e.turn for e in self.evidence if e.session_id == session_id})


def scope_name(scope: str) -> str:
    return "global" if scope == GLOBAL else PurePath(scope).name or scope


def _one_of[T: str](value: object, allowed: Sequence[T], default: T) -> T:
    return next((a for a in allowed if a == value), default)


def normalized(statement: str) -> str:
    """For telling repeats apart from new items: case, punctuation and spacing ignored."""
    return " ".join(re.findall(r"[a-z0-9]+", statement.lower()))
