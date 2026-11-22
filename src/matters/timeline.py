"""How a session's time was spent, from the record alone: no model, no guessing at intent.

Every step gets an activity and a duration:

    you       reading the last answer and writing the next ask
    discuss   the assistant talking: planning, explaining, answering
    explore   reading code and docs, searching, inspecting
    build     editing files, installing, scaffolding
    verify    tests, linters, type checks, builds, smoke tests
    debug     anything between a failed check and the next passing one
    run       serving, stopping, deploying, version control

Durations come from timestamps: a step lasts until the next thing happened (a
tool until its result came back). Gaps are capped, so a lunch break doesn't
count as work; what's cut off is reported as time away.

What the conversation was *about* (architecture, low-level design, ...) needs
judgment and lives in matters.focus.
"""

import re
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from matters.clock import moment, seconds_between
from matters.session import NO_TOKENS, Entry, Session, Tokens

type Activity = Literal["you", "discuss", "explore", "build", "verify", "debug", "run"]
ACTIVITIES: tuple[Activity, ...] = ("you", "discuss", "explore", "build", "verify", "debug", "run")

STEP_CAP = 10 * 60  # seconds: longer than this, the assistant wasn't the one busy
YOU_CAP = 15 * 60  # seconds: longer than this between turns, you were away
KEPT = 1024  # timelines kept: every page's rail shows every session's work time

_EXPLORE_TOOLS = frozenset(
    {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "ToolSearch", "Skill", "Agent", "Task"}
)
_BUILD_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit", "Artifact"})
_DISCUSS_TOOLS = frozenset({"TodoWrite", "AskUserQuestion", "ExitPlanMode", "EnterPlanMode"})

_VERIFY = re.compile(
    r"\b(pytest|ruff|mypy|pyright|tox|nox|unittest|make\s+(check|test|lint|typecheck|format-check)"
    r"|(npm|pnpm|yarn|bun)\s+(run\s+)?(test|lint|check|typecheck)|jest|vitest|tsc|eslint|prettier\s+--check"
    r"|cargo\s+(test|check|clippy)|go\s+(test|vet)|rspec|rubocop|phpunit|(gradlew?|mvn)\s+\S*test"
    r"|curl\b[^|;&]*(localhost|127\.0\.0\.1))"
)
_RUN = re.compile(
    r"\b(serve|nohup|restart|docker|kubectl|deploy|git\s+(push|commit|checkout|switch|merge|rebase|tag)"
    r"|matters\s+stop|kill|lsof\s+-i)"
)
_BUILD = re.compile(
    r"(\bsed\s+-i|\bperl\s+-\w*i|\bmkdir\b|\bcp\b|\bmv\b|\brm\b|\btouch\b|\bchmod\b|\bln\s+-s"
    r"|\buv\s+(add|remove|sync|init)|\bpip\s+install|\b(npm|pnpm|yarn|bun)\s+(install|add|i)\b"
    r"|\bgit\s+(add|apply|init)|write_text\(|open\([^)]*['\"][wa]['\"]|(?<![0-9&])>>?\s*[\w./~$\"'])"
)
_HARMLESS_REDIRECTS = re.compile(r"\d?>\s*/dev/null|\d>&\d|&>\s*/dev/null")


@dataclass(frozen=True, slots=True)
class Step:
    """One measured step, in session order."""

    activity: Activity
    turn: int  # 1-based, as on the page; 0 before the first ask
    seconds: float
    failed: bool = False
    tokens: Tokens = NO_TOKENS


@dataclass(frozen=True, slots=True)
class Segment:
    """Neighbouring steps with the same activity, merged for drawing."""

    activity: Activity
    turn: int
    start: float  # seconds of active time since the session started
    seconds: float
    steps: int
    failed: int = 0
    tokens: Tokens = NO_TOKENS

    @classmethod
    def starting(cls, step: Step, start: float) -> "Segment":
        return cls(step.activity, step.turn, start, step.seconds, 1, int(step.failed), step.tokens)

    def extended(self, step: Step) -> "Segment":
        """This segment with one more step of the same activity."""
        return replace(
            self,
            seconds=self.seconds + step.seconds,
            steps=self.steps + 1,
            failed=self.failed + step.failed,
            tokens=self.tokens + step.tokens,
        )

    @property
    def is_visible(self) -> bool:
        return bool(self.seconds > 0 or self.failed or self.tokens.total)

    @classmethod
    def merged(cls, steps: list[Step]) -> tuple["Segment", ...]:
        """Neighbouring steps of one activity as one segment; empty ones left out."""
        segments: list[Segment] = []
        clock = 0.0
        for step in steps:
            if segments and segments[-1].activity == step.activity:
                segments[-1] = segments[-1].extended(step)
            else:
                segments.append(cls.starting(step, clock))
            clock += step.seconds
        return tuple(s for s in segments if s.is_visible)


@dataclass(frozen=True, slots=True)
class Timeline:
    steps: tuple[Step, ...]
    segments: tuple[Segment, ...]
    away: tuple[tuple[float, float], ...] = ()  # (position in active seconds, seconds away)
    turn_spans: dict[int, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def of(cls, session: Session) -> "Timeline":
        """The session's timeline, drawn once for as long as the session is the same: a
        source hands out the same session until its file changes."""
        kept = _drawn.get(id(session))
        if kept and kept[0] is session:
            _drawn.move_to_end(id(session))
            return kept[1]
        line = cls.walked(session)
        _drawn[id(session)] = (session, line)
        while len(_drawn) > KEPT:
            _drawn.popitem(last=False)
        return line

    @classmethod
    def walked(cls, session: Session) -> "Timeline":
        """Walk the session with one clock: each step owns the time since the previous
        event (a record is written when its step is done) plus, for a tool, its running
        time."""
        entries = [e for e in session.entries if not e.is_event]
        steps: list[Step] = []
        away: list[tuple[float, float]] = []
        clock, turn, debugging = 0.0, 0, False
        last: datetime | None = None
        for entry, activity in zip(entries, _planned(entries), strict=True):
            if entry.is_ask:
                turn += 1
            if activity == "verify":
                debugging = entry.failed
            elif debugging and activity in ("build", "explore", "discuss"):
                activity = "debug"
            at = moment(entry.at)
            end = moment(entry.tool.finished_at) if entry.tool else None
            waited, ran = seconds_between(last, at), seconds_between(at, end)
            cap = YOU_CAP if activity == "you" else STEP_CAP
            if waited > cap:
                away.append((clock, waited - cap))
                waited = cap
            if ran > STEP_CAP:
                away.append((clock + waited + STEP_CAP, ran - STEP_CAP))
                ran = STEP_CAP
            steps.append(
                Step(activity, turn, waited + ran, entry.failed, entry.tokens or NO_TOKENS)
            )
            clock += waited + ran
            last = max((t for t in (last, at, end) if t is not None), default=None)
        return cls(tuple(steps), Segment.merged(steps), tuple(away), _turn_spans(steps))

    @property
    def away_seconds(self) -> float:
        return sum(seconds for _, seconds in self.away)

    @property
    def active_seconds(self) -> float:
        return sum(s.seconds for s in self.steps)

    def seconds_in(self, activity: Activity) -> float:
        return sum(s.seconds for s in self.steps if s.activity == activity)

    def tokens_in(self, activity: Activity | None = None) -> Tokens:
        return sum(
            (s.tokens for s in self.steps if activity is None or s.activity == activity), NO_TOKENS
        )

    @property
    def turn_tokens(self) -> dict[int, Tokens]:
        totals: dict[int, Tokens] = {}
        for step in self.steps:
            if step.turn:
                totals[step.turn] = totals.get(step.turn, NO_TOKENS) + step.tokens
        return totals

    @property
    def checks(self) -> int:
        return sum(1 for s in self.steps if s.activity == "verify")

    @property
    def failed_checks(self) -> int:
        return sum(1 for s in self.steps if s.activity == "verify" and s.failed)

    @property
    def cycles(self) -> int:
        """Build-then-verify rounds that ended green: how many times the work was proven."""
        count, built = 0, False
        for step in self.steps:
            if step.activity in ("build", "debug"):
                built = True
            elif step.activity == "verify" and not step.failed and built:
                count, built = count + 1, False
        return count


# id -> (the session, its timeline); the session is kept so its id is not reused meanwhile.
_drawn: OrderedDict[int, tuple[Session, Timeline]] = OrderedDict()


def classify(entry: Entry) -> Activity:
    """The activity of one step, before debug periods are applied."""
    if entry.is_ask:
        return "you"
    if not entry.tool:
        return "discuss"
    name = entry.tool.name
    if name == "Bash":
        return _shell(str(entry.tool.input.get("command", "")))
    if name in _BUILD_TOOLS:
        return "build"
    if name in _DISCUSS_TOOLS:
        return "discuss"
    if name in _EXPLORE_TOOLS or name.startswith("mcp__"):
        return "explore"
    return "explore"


def _shell(command: str) -> Activity:
    command = _HARMLESS_REDIRECTS.sub(" ", command)
    if _VERIFY.search(command):
        return "verify"
    if _RUN.search(command):
        return "run"
    if _BUILD.search(command):
        return "build"
    return "explore"


def _planned(entries: list[Entry]) -> list[Activity]:
    """The assistant's words and thinking take the activity of the tool they lead to;
    only what it says with no tool after it, in that turn, is discussion."""
    activities = [classify(e) for e in entries]
    upcoming: Activity | None = None
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if entry.is_ask:
            upcoming = None
        elif entry.tool:
            upcoming = activities[index]
        elif upcoming is not None:
            activities[index] = upcoming
    return activities


def _turn_spans(steps: list[Step]) -> dict[int, tuple[float, float]]:
    """turn -> (start, end) in active seconds, your reading time excluded."""
    spans: dict[int, tuple[float, float]] = {}
    clock = 0.0
    for step in steps:
        if step.activity != "you" and step.turn:
            start, _ = spans.get(step.turn, (clock, clock))
            spans[step.turn] = (start, clock + step.seconds)
        clock += step.seconds
    return spans
