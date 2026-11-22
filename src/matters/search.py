"""Full-text search over every session: what you asked, what the assistant answered, and the
work in between (commands, edits, their output, the assistant's notes to itself).

A query is words and "quoted phrases"; a block matches when it holds all of them, in
any case. In each session, what was said (asks, then answers) comes before the work,
which matches far more often and matters less. A block is one ask, one answer, or one
step of work, so a hit always lands on a turn the page can scroll to. File contents the
assistant only read (Read, WebFetch) are left out: searching them would find every file,
not the conversation.
"""

import json
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

from matters.session import Entry, Session, ToolCall

type Where = Literal["ask", "answer", "work"]
WHERES: tuple[Where, ...] = ("ask", "answer", "work")
WHERE_LABELS: dict[Where, str] = {"ask": "Asks", "answer": "Answers", "work": "Work"}

_UNREAD_RESULTS = frozenset({"Read", "NotebookRead", "WebFetch"})
_TERMS = re.compile(r'"([^"]+)"|(\S+)')


@dataclass(frozen=True, slots=True)
class Hit:
    session: Session
    turn: int  # 1-based, as on the page
    where: Where
    label: str  # "You asked", "Answer", "Bash", "Edit"…
    text: str  # the block that matched
    entry: Entry

    @classmethod
    def blocks_in(cls, session: Session) -> Iterator["Hit"]:
        """Every block a search can land on: each ask, each step of work, each answer."""
        for turn in session.turns:
            n = turn.number
            if turn.ask:
                yield cls(session, n, "ask", "You asked", turn.ask.text, turn.ask)
            for step in turn.work:
                if step.tool:
                    yield cls(session, n, "work", step.tool.name, _searchable(step.tool), step)
                elif step.kind == "text":
                    yield cls(session, n, "work", "Note", step.text, step)
            if turn.answer:
                yield cls(session, n, "answer", "Answer", turn.answer.text, turn.answer)

    def holds(self, terms: Sequence[str]) -> bool:
        lower = self.text.lower()
        return all(term in lower for term in terms)


@dataclass(frozen=True, slots=True)
class Results:
    terms: tuple[str, ...]
    hits: tuple[Hit, ...]  # sessions newest first; in each, the conversation before the work
    counts: dict[Where, int]  # hits per kind, before filtering by kind

    @classmethod
    def search(
        cls, sessions: Sequence[Session], query: str, where: Where | None = None
    ) -> "Results":
        wanted = terms(query)
        if not wanted:
            return cls((), (), dict.fromkeys(WHERES, 0))
        newest = sorted(sessions, key=lambda s: s.ended_at or s.started_at or "", reverse=True)
        every = [
            hit
            for session in newest
            for hit in sorted(
                (h for h in Hit.blocks_in(session) if h.holds(wanted)),
                key=lambda h: (WHERES.index(h.where), h.turn),
            )
        ]
        counts = Counter(h.where for h in every)
        chosen = tuple(h for h in every if where in (None, h.where))
        return cls(wanted, chosen, {w: counts[w] for w in WHERES})

    def by_session(self) -> list[tuple[Session, list[Hit]]]:
        grouped: dict[str, tuple[Session, list[Hit]]] = {}
        for hit in self.hits:
            grouped.setdefault(hit.session.id, (hit.session, []))[1].append(hit)
        return list(grouped.values())


def terms(query: str) -> tuple[str, ...]:
    """Words and "quoted phrases", lower-cased, each once."""
    found = (phrase or word for phrase, word in _TERMS.findall(query))
    return tuple(dict.fromkeys(t.strip().lower() for t in found if t.strip()))


def _searchable(call: ToolCall) -> str:
    """A call's text: what it was given, and what came back unless it only read a file."""
    values = [v for v in call.input.values() if isinstance(v, str)]
    if not values and call.input:
        values = [json.dumps(call.input, ensure_ascii=False)]
    result = "" if call.name in _UNREAD_RESULTS else call.result or ""
    return "\n".join([*values, result]).strip()


def excerpt(text: str, wanted: Sequence[str], width: int = 220) -> list[tuple[str, bool]]:
    """A window of the text around the first match, as (piece, is_match) runs, so the page
    can mark every term without parsing HTML. Whitespace is collapsed."""
    flat = " ".join(text.split())
    lower = flat.lower()
    first = min((i for t in wanted if (i := lower.find(t)) >= 0), default=0)
    start = max(0, first - width // 3)
    if start:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < first else start
    window = flat[start : start + width]
    runs = _marked(window, wanted)
    if start:
        runs.insert(0, ("…", False))
    if start + width < len(flat):
        runs.append(("…", False))
    return runs


def _marked(text: str, wanted: Sequence[str]) -> list[tuple[str, bool]]:
    if not wanted:
        return [(text, False)]
    pattern = re.compile(
        "|".join(re.escape(t) for t in sorted(wanted, key=len, reverse=True)), re.I
    )
    runs: list[tuple[str, bool]] = []
    at = 0
    for match in pattern.finditer(text):
        if match.start() > at:
            runs.append((text[at : match.start()], False))
        runs.append((match.group(0), True))
        at = match.end()
    if at < len(text):
        runs.append((text[at:], False))
    return runs
