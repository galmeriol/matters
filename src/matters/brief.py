"""Where a project stands, from its sessions alone: no model, nothing sent anywhere.

What you need when you come back to a project:

    where you left off   the latest session's last ask and answer
    still open           how each session ended, when it ended unfinished: a question
                         the assistant asked you, a check that was still failing, an
                         ask that got no answer, or work you interrupted
    files touched        every file edited, most recent first, with the turns that did it
    sessions             all of them, newest first

Every item points at its turn and source line.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from matters.links import editor_url
from matters.session import Entry, Session, SourceRef, Turn
from matters.timeline import classify

type Ending = Literal["question", "failing", "unanswered", "interrupted"]
ENDING_LABELS: dict[Ending, str] = {
    "question": "Asked you",
    "failing": "Still failing",
    "unanswered": "No answer",
    "interrupted": "Interrupted",
}


@dataclass(frozen=True, slots=True)
class Loose:
    """A session that ended unfinished, and how."""

    session: Session
    turn: int
    ending: Ending
    text: str
    ref: SourceRef

    @classmethod
    def of(cls, session: Session) -> "Loose | None":
        """How the session ended, if it ended unfinished: judged by its last ask."""
        last = next(((t, t.ask) for t in reversed(session.turns) if t.ask), None)
        if last is None:
            return None
        turn, ask = last

        def loose(ending: Ending, text: str, ref: SourceRef) -> Loose:
            return cls(session, turn.number, ending, text, ref)

        if _interrupted(turn):
            return loose("interrupted", ask.text, ask.ref)
        if failing := _failing_check(turn):
            return loose("failing", *failing)
        if turn.answer is None:
            return loose("unanswered", ask.text, ask.ref)
        if question := _closing_question(turn.answer.text):
            return loose("question", question, turn.answer.ref)
        return None

    def to_markdown(self) -> str:
        label = ENDING_LABELS[self.ending]
        return f"- {label}: {_link(self.text, self.ref)} ({_flat(self.session.headline, 60)})"


@dataclass(frozen=True, slots=True)
class Touch:
    """One edit that changed a file: which session, which turn. Failed edits changed
    nothing, so they aren't touches."""

    session: Session
    turn: int
    ref: SourceRef


@dataclass(frozen=True, slots=True)
class FileHistory:
    path: str  # relative to the project when inside it
    absolute: str
    touches: tuple[Touch, ...]  # newest first

    @classmethod
    def all_in(cls, sessions: Sequence[Session], project: Path) -> list["FileHistory"]:
        """Every file these sessions changed, the most recently changed first."""
        touches: dict[str, list[Touch]] = {}
        for session in sessions:  # newest first
            for turn in reversed(session.turns):
                for step in reversed(turn.steps):
                    for path in step.changed:
                        touches.setdefault(path, []).append(Touch(session, turn.number, step.ref))
        return [
            cls(path.removeprefix(f"{project}/"), path, tuple(found))
            for path, found in touches.items()
        ]

    @property
    def edits(self) -> int:
        return len(self.touches)

    def to_markdown(self) -> str:
        last = self.touches[0]
        edits = f"{self.edits} edit{'s' if self.edits != 1 else ''}"
        where = _link(_flat(last.session.headline, 60), last.ref)
        file = f"[{self.path}](vscode://file{self.absolute})"
        return f"- {file} · {edits} · last in {where}, turn {last.turn}"

    @property
    def sessions(self) -> int:
        return len({t.session.id for t in self.touches})


@dataclass(frozen=True, slots=True)
class Brief:
    project: Path
    sessions: tuple[Session, ...]  # newest first
    loose: tuple[Loose, ...] = ()
    files: tuple[FileHistory, ...] = ()  # inside the project
    outside: int = 0  # files edited elsewhere (scratch files, other repos)
    last: Turn | None = field(default=None)  # the latest session's last turn with an ask

    @classmethod
    def of(cls, sessions: Sequence[Session], project: Path) -> "Brief":
        mine = sorted(
            (s for s in sessions if s.project == project and not s.is_empty),
            key=lambda s: s.ended_at or s.started_at or "",
            reverse=True,
        )
        last = next((t for t in reversed(mine[0].turns) if t.ask), None) if mine else None
        files = FileHistory.all_in(mine, project)
        inside = tuple(f for f in files if f.absolute.startswith(f"{project}/"))
        loose = tuple(found for s in mine if (found := Loose.of(s)))
        return cls(project, tuple(mine), loose, inside, len(files) - len(inside), last)

    @property
    def latest(self) -> Session | None:
        return self.sessions[0] if self.sessions else None

    def to_markdown(self) -> str:
        """Every line linked to its source: for the terminal (`matters brief`) and for
        pasting into a new session."""
        out = [f"# {self.project.name or self.project}", ""]
        first = self.sessions[-1].started_at if self.sessions else None
        span = f" · {(first or '')[:10]} – {((self.latest and self.latest.ended_at) or '')[:10]}"
        count = len(self.sessions)
        out += [f"{self.project} · {count} session{'s' if count != 1 else ''}{span}"]
        if self.latest and (turn := self.last):
            out += ["", "## Where you left off", ""]
            out += [f"{_link(self.latest.headline, self.latest.ref)} · turn {turn.number}", ""]
            if turn.ask:
                out += [_quote(turn.ask)]
            if turn.answer:
                out += ["", turn.answer.text.strip()]
            out += ["", f"Resume: `cd {self.project} && claude --resume {self.latest.id}`"]
        if self.loose:
            out += ["", "## Still open", ""]
            out += [loose.to_markdown() for loose in self.loose]
        if self.files:
            out += ["", "## Files touched", ""]
            out += [file.to_markdown() for file in self.files]
        out += ["", "## Sessions", ""]
        out += [_session_line(s) for s in self.sessions]
        return "\n".join(out) + "\n"


def _interrupted(turn: Turn) -> bool:
    """Interrupted, and not answered after: the human stopped it and moved on."""
    kinds = [step.kind for step in turn.steps]
    if "interrupt" not in kinds:
        return False
    return "text" not in kinds[kinds.index("interrupt") + 1 :]


def _failing_check(turn: Turn) -> tuple[str, SourceRef] | None:
    """The turn's last check (tests, lint, types), if it failed: what ran, and where."""
    checks = [(s, s.tool) for s in turn.steps if s.tool and classify(s) == "verify"]
    if not checks or not checks[-1][1].is_error:
        return None
    step, call = checks[-1]
    command = str(call.input.get("description") or call.input.get("command") or "")
    return " ".join(command.split()), step.ref


def _closing_question(answer: str) -> str:
    """The answer's last line, when it asks something."""
    lines = [line.strip() for line in answer.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    last = lines[-1].strip("*_ ")
    return last if last.endswith("?") else ""


def _session_line(session: Session) -> str:
    title = _link(_flat(session.headline, 90), session.ref)
    return f"- {(session.started_at or '')[:10]} {title} · {len(session.asks)} asks"


def _quote(ask: Entry) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in ask.text.strip().splitlines())


def _flat(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _link(text: str, ref: SourceRef) -> str:
    label = _flat(text, 120).replace("[", "(").replace("]", ")")
    return f"[{label}]({editor_url(ref)})"
