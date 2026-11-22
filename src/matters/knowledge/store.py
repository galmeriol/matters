"""Knowledge, kept: candidates waiting for review, what was accepted, what was rejected
(so it is not proposed again), and which sessions were read."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from matters.db import connect
from matters.errors import DataError
from matters.knowledge.model import Draft, Evidence, Item, normalized
from matters.session import Session

type Action = Literal["accept", "reject", "restore", "save"]
ACTIONS: tuple[Action, ...] = ("accept", "reject", "restore", "save")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL,             -- "global" or a project path
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    why TEXT NOT NULL,
    basis TEXT NOT NULL,             -- stated | reaction
    evidence TEXT NOT NULL,          -- [{"session_id", "turn", "quote"}]
    status TEXT NOT NULL,            -- candidate | accepted | rejected
    relation TEXT NOT NULL,          -- new | updates | contradicts
    related_id INTEGER,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS knowledge_runs (
    session_id TEXT NOT NULL,
    entries INTEGER NOT NULL,        -- how long the session was when read
    created_at TEXT NOT NULL
);
"""
_COLUMNS = (
    "id, kind, scope, category, statement, why, basis, evidence, status, relation, related_id,"
    " model, created_at, decided_at"
)


@dataclass(frozen=True, slots=True)
class Added:
    """What one extraction left in the store, by item id."""

    new: tuple[int, ...] = ()  # candidates to review
    merged: tuple[int, ...] = ()  # known items a repeat added evidence to
    skipped: int = 0  # repeats of rejected items, dropped


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class KnowledgeStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with connect(path) as db:
            db.executescript(_SCHEMA)

    def add(self, drafts: Iterable[Draft], model: str) -> Added:
        """Store proposals. A repeat of a known item adds its evidence to that item;
        a repeat of a rejected one is dropped; the rest wait for review."""
        new: list[int] = []
        merged: list[int] = []
        skipped = 0
        items = self.all()
        by_text = {normalized(i.statement): i for i in items}
        by_id = {i.id: i for i in items}
        for draft in drafts:
            same = by_text.get(normalized(draft.statement))
            if same is None and draft.relation == "duplicate" and draft.related_id:
                same = by_id.get(draft.related_id)
            if same is not None and same.status == "rejected":
                skipped += 1
                continue
            if same is not None:
                grown = self._add_evidence(same, draft.evidence)
                by_text[normalized(same.statement)] = by_id[same.id] = grown
                merged.append(same.id)
                continue
            item = self._insert(draft, model)
            by_text[normalized(item.statement)] = by_id[item.id] = item
            new.append(item.id)
        return Added(tuple(new), tuple(dict.fromkeys(merged)), skipped)

    def _insert(self, draft: Draft, model: str) -> Item:
        relation = "new" if draft.relation == "duplicate" else draft.relation
        with connect(self.path) as db:
            cursor = db.execute(
                "INSERT INTO knowledge (kind, scope, category, statement, why, basis, evidence,"
                " status, relation, related_id, model, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?)",
                (
                    draft.kind,
                    draft.scope,
                    draft.category,
                    draft.statement,
                    draft.why,
                    draft.basis,
                    Evidence.to_json(draft.evidence),
                    relation,
                    draft.related_id,
                    model,
                    _now(),
                ),
            )
            new_id = int(cursor.lastrowid or 0)
        if (found := self.get(new_id)) is None:
            raise DataError(f"Knowledge item {new_id} was saved but can't be read back.")
        return found

    def _add_evidence(self, item: Item, evidence: Sequence[Evidence]) -> Item:
        seen = {(e.session_id, e.turn) for e in item.evidence}
        more = tuple(e for e in evidence if (e.session_id, e.turn) not in seen)
        if not more:
            return item
        grown = replace(item, evidence=item.evidence + more)
        with connect(self.path) as db:
            db.execute(
                "UPDATE knowledge SET evidence = ? WHERE id = ?",
                (Evidence.to_json(grown.evidence), item.id),
            )
        return grown

    def all(self) -> list[Item]:
        with connect(self.path) as db:
            rows = db.execute(f"SELECT {_COLUMNS} FROM knowledge ORDER BY id DESC").fetchall()
        return [Item.from_row(row) for row in rows]

    def with_status(self, status: str) -> list[Item]:
        return [i for i in self.all() if i.status == status]

    def get(self, item_id: int) -> Item | None:
        with connect(self.path) as db:
            row = db.execute(
                f"SELECT {_COLUMNS} FROM knowledge WHERE id = ?", (item_id,)
            ).fetchone()
        return Item.from_row(row) if row else None

    def decide(
        self, ids: Iterable[int], action: Action, edits: dict[int, tuple[str, str]] | None = None
    ) -> int:
        """Accept, reject, restore to review, or only save edits (statement, scope).
        Accepting an update or a contradiction retires the item it replaces."""
        edits = edits or {}
        status = {"accept": "accepted", "reject": "rejected", "restore": "candidate"}.get(action)
        changed = 0
        with connect(self.path) as db:
            for item_id in ids:
                row = db.execute(
                    "SELECT relation, related_id FROM knowledge WHERE id = ?", (item_id,)
                ).fetchone()
                if row is None:
                    continue
                if item_id in edits:
                    statement, scope = edits[item_id]
                    if statement.strip():
                        db.execute(
                            "UPDATE knowledge SET statement = ?, scope = ? WHERE id = ?",
                            (" ".join(statement.split()), scope, item_id),
                        )
                if status:
                    db.execute(
                        "UPDATE knowledge SET status = ?, decided_at = ? WHERE id = ?",
                        (status, _now() if status != "candidate" else "", item_id),
                    )
                    relation, related = row
                    if status == "accepted" and relation in ("updates", "contradicts") and related:
                        db.execute(
                            "UPDATE knowledge SET status = 'rejected', decided_at = ?"
                            " WHERE id = ? AND status = 'accepted'",
                            (_now(), related),
                        )
                changed += 1
        return changed

    def read(self, sessions: Iterable[Session]) -> None:
        """Remember that these sessions were read, and how long they were."""
        with connect(self.path) as db:
            db.executemany(
                "INSERT INTO knowledge_runs (session_id, entries, created_at) VALUES (?, ?, ?)",
                [(s.id, len(s.entries), _now()) for s in sessions],
            )

    def read_sessions(self) -> frozenset[str]:
        with connect(self.path) as db:
            rows = db.execute("SELECT DISTINCT session_id FROM knowledge_runs").fetchall()
        return frozenset(str(r[0]) for r in rows)
