"""What the model reads: selected sessions as a compact, citable transcript.

Each session gets an alias (S1, S2, ...) and each turn its number, so the model
can cite "S2:t5" and the page can link that back to /s/<id>#t5, the same
anchor the session page uses. The human's words are kept in full; pasted text,
tool work and the assistant's prose are shortened, in that order, to fit the
budget. Whatever was shortened is reported, never silently dropped.
"""

import os
from dataclasses import dataclass, field
from html import escape
from typing import Any

from matters.redact import redact
from matters.session import Entry, Session, Turn


@dataclass(frozen=True, slots=True)
class Detail:
    """How much of each kind of content goes in, in characters; it writes the transcript
    at that level."""

    pasted: int
    answer: int
    note: int
    work: bool

    @property
    def shortened(self) -> str:
        """The note that says what this level left out."""
        work = "" if self.work else ", tool work left out"
        return (
            f"Shortened to fit: pasted text to {self.pasted:,} characters, "
            f"answers to {self.answer:,}{work}."
        )

    def write(self, alias: str, session: Session) -> str:
        head = (
            f'<session id="{alias}" project="{_attr(session.project.name)}" '
            f'started="{_attr(session.started_at or "")}" title="{_attr(session.title or "")}">'
        )
        body = "\n".join(self.turn(turn) for turn in session.turns)
        return f"{head}\n{body}\n</session>"

    def turn(self, turn: Turn) -> str:
        lines = [f'<turn n="{turn.number}">']
        if turn.ask:
            lines.extend(self.ask(turn.ask))
        if self.work and (work := "\n".join(filter(None, map(self.step, turn.work)))):
            lines.append(f"<work>\n{work}\n</work>")
        if turn.answer:
            lines.append(f"<assistant>{_clip(turn.answer.text, self.answer)}</assistant>")
        lines.extend(f"<event>{e.kind}: {_clip(e.text, 200)}</event>" for e in turn.events)
        lines.append("</turn>")
        return "\n".join(lines)

    def ask(self, ask: Entry) -> list[str]:
        if not ask.parts:
            return [f"<human>{_text(ask.text)}</human>"]
        words: list[str] = []
        extras: list[str] = []
        for part in ask.parts:
            match part.kind:
                case "text" | "queued":
                    words.append(part.text)
                case "pasted":
                    body = _clip(part.text, self.pasted)
                    extras.append(f'<pasted size="{_attr(part.label)}">{body}</pasted>')
                case "selection":
                    extras.append(f"<selection>{_clip(part.text, self.pasted // 2)}</selection>")
                case "file":
                    extras.append(f"<context>open in editor: {_text(part.text)}</context>")
                case "image":
                    extras.append("<context>attached an image</context>")
                case "output":
                    extras.append(f"<context>command output: {_clip(part.text, 300)}</context>")
                case _:
                    pass  # reminders and notifications are the tool talking, not the human
        said = " ".join(w for w in words if w.strip())
        return ([f"<human>{_text(said)}</human>"] if said else []) + extras

    def step(self, step: Entry) -> str:
        if (call := step.tool) and call.name == "AskUserQuestion" and call.result:
            # The human choosing between options: as telling as anything they typed.
            return f"- asked the human; they answered: {_clip(call.result, 1500)}"
        if call:
            failed = " (failed)" if call.is_error else ""
            target = _clip(_target(call.input), 160)
            return f"- {_text(call.name)}{f': {target}' if target else ''}{failed}"
        if step.kind == "text" and self.note:
            return f"- said: {_clip(step.text, self.note)}"
        return ""  # thinking stays out: it is the assistant's draft, not what was agreed


# From most to least generous; the first that fits the budget wins.
LEVELS = (
    Detail(pasted=3000, answer=5000, note=800, work=True),
    Detail(pasted=1200, answer=2500, note=300, work=True),
    Detail(pasted=400, answer=1200, note=0, work=True),
    Detail(pasted=150, answer=500, note=0, work=False),
)
DEFAULT_BUDGET = 600_000  # characters, about 170k tokens


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    aliases: dict[str, str]  # "S1" -> session id
    turns: dict[str, int]  # session id -> number of turns
    clipped: tuple[str, ...] = field(default=())
    written: str = ""  # instruction files the developer already keeps (see knowledge.instructions)

    @classmethod
    def build(cls, sessions: list[Session], limit: int | None = None) -> "Transcript":
        """Oldest session first, so reversals read in the order they happened; at the most
        generous level that fits the budget."""
        limit = limit or budget()
        ordered = sorted(sessions, key=lambda s: s.started_at or "")
        aliases = {f"S{n}": s.id for n, s in enumerate(ordered, start=1)}
        turns = {s.id: len(s.turns) for s in ordered}
        text = ""
        for detail in LEVELS:
            text = "\n\n".join(detail.write(a, s) for a, s in zip(aliases, ordered, strict=True))
            if len(text) <= limit:
                notes = () if detail is LEVELS[0] else (detail.shortened,)
                return cls(text, aliases, turns, notes)
        note = (
            f"The selection is larger than the budget ({len(text):,} > {limit:,} characters): "
            "the newest material was cut off. Pick fewer sessions, or raise MATTERS_MAP_BUDGET."
        )
        cut = text[:limit] + "\n[TRANSCRIPT CUT HERE]"
        return cls(cut, aliases, turns, (LEVELS[-1].shortened, note))

    @staticmethod
    def size_of(session: Session) -> int:
        """Characters a session adds at the most generous level: for estimates on the page."""
        return len(LEVELS[0].write("S1", session))

    @property
    def tokens(self) -> int:
        return estimate_tokens(len(self.text))


def estimate_tokens(chars: int) -> int:
    return round(chars / 3.5)


def budget() -> int:
    try:
        return int(os.environ.get("MATTERS_MAP_BUDGET", DEFAULT_BUDGET))
    except ValueError:
        return DEFAULT_BUDGET


_TARGET_KEYS = (
    "description", "command", "file_path", "notebook_path", "pattern", "url", "query", "prompt",
)  # fmt: skip


def _target(tool_input: dict[str, Any]) -> str:
    for key in _TARGET_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return _text(text)
    return _text(text[:limit]) + f" […{len(text) - limit:,} more characters]"


def _text(text: str) -> str:
    return escape(redact(text), quote=False)


def _attr(text: str) -> str:
    return escape(redact(text), quote=True)
