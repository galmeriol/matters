"""The normalised journal: what every source produces and everything else reads."""

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar, Literal

from matters.clock import is_recent, moment, seconds_between

type Kind = Literal["ask", "text", "thinking", "tool", "command", "interrupt", "notice"]
type PartKind = Literal[
    "text", "pasted", "file", "selection", "image", "reminder", "notification", "output", "queued"
]

EVENT_KINDS = frozenset({"command", "interrupt", "notice"})

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where something came from.

    Traceability is the product's invariant: whatever ends up on a page
    can be opened at its source line.
    """

    path: Path
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True, slots=True)
class Tokens:
    """What one model call consumed, as the session recorded it."""

    input: int = 0  # fresh input, not from the cache
    output: int = 0  # including thinking
    cache_write: int = 0
    cache_read: int = 0

    # Roughly what each kind costs relative to fresh input on Claude models.
    WEIGHTS: ClassVar[tuple[float, ...]] = (1.0, 5.0, 1.25, 0.1)

    @classmethod
    def from_usage(cls, usage: Mapping[str, Any]) -> "Tokens":
        """From a Messages API `usage` object; a missing or odd count is zero."""

        def count(name: str) -> int:
            value = usage.get(name)
            return value if isinstance(value, int) else 0

        return cls(
            count("input_tokens"),
            count("output_tokens"),
            count("cache_creation_input_tokens"),
            count("cache_read_input_tokens"),
        )

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_write + self.cache_read

    @property
    def weight(self) -> float:
        """Cost-weighted tokens: for comparing consumption, not for billing."""
        counts = (self.input, self.output, self.cache_write, self.cache_read)
        return sum(n * w for n, w in zip(counts, self.WEIGHTS, strict=True))

    def __add__(self, other: "Tokens") -> "Tokens":
        return Tokens(
            self.input + other.input,
            self.output + other.output,
            self.cache_write + other.cache_write,
            self.cache_read + other.cache_read,
        )


NO_TOKENS = Tokens()


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool the assistant used, paired with what came back."""

    name: str
    input: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    is_error: bool = False
    finished_at: str | None = None  # when the result came back (ISO 8601)
    id: str = ""  # the source's id for the call, to pair it with what it started
    outcome: dict[str, Any] = field(default_factory=dict)  # the result as structured data

    @property
    def edited_file(self) -> str | None:
        if self.name not in EDIT_TOOLS:
            return None
        path = self.input.get("file_path") or self.input.get("notebook_path")
        return str(path) if path else None


@dataclass(frozen=True, slots=True)
class Part:
    """A piece of what the human sent: their own words, or something that came with them
    (pasted text, an open file, a selection, an image, a reminder, command output)."""

    kind: PartKind
    text: str = ""
    label: str = ""
    media_type: str = ""


@dataclass(frozen=True, slots=True)
class Entry:
    """One normalised event: something the human asked, one step of the assistant's work,
    or something that happened in the tool (a command, an interruption, a notice)."""

    kind: Kind
    text: str
    ref: SourceRef
    tool: ToolCall | None = None
    parts: tuple[Part, ...] = ()
    at: str | None = None  # when it was recorded (ISO 8601)
    tokens: Tokens | None = None  # set on the first step of each model call

    @property
    def is_ask(self) -> bool:
        return self.kind == "ask"

    @property
    def is_event(self) -> bool:
        return self.kind in EVENT_KINDS

    @property
    def failed(self) -> bool:
        return bool(self.tool and self.tool.is_error)

    @property
    def files(self) -> tuple[str, ...]:
        """The file this step set out to edit, whether or not the edit took."""
        edited = self.tool.edited_file if self.tool else None
        return (edited,) if edited else ()

    @property
    def changed(self) -> tuple[str, ...]:
        """The files this step actually changed: a failed edit changed nothing."""
        return () if self.failed else self.files


@dataclass(frozen=True, slots=True)
class Turn:
    """What the human asked, and everything the assistant did about it."""

    number: int  # 1-based, as on the page
    ask: Entry | None
    steps: tuple[Entry, ...]

    @classmethod
    def from_entries(cls, number: int, entries: Sequence[Entry]) -> "Turn":
        """An ask and the steps after it, or (before the first ask) steps alone."""
        first, *rest = entries
        return (
            cls(number, first, tuple(rest)) if first.is_ask else cls(number, None, tuple(entries))
        )

    @property
    def answer(self) -> Entry | None:
        """The assistant's last words in this turn: what the human actually read."""
        return next((step for step in reversed(self.steps) if step.kind == "text"), None)

    @property
    def work(self) -> tuple[Entry, ...]:
        """The assistant's steps except the answer: the part worth folding away."""
        answer = self.answer
        return tuple(s for s in self.steps if s is not answer and not s.is_event)

    @property
    def events(self) -> tuple[Entry, ...]:
        """Commands, interruptions and notices: shown, never folded into work."""
        return tuple(step for step in self.steps if step.is_event)

    @property
    def tool_counts(self) -> dict[str, int]:
        """Each tool the assistant used, most used first."""
        return dict(Counter(s.tool.name for s in self.steps if s.tool).most_common())

    @property
    def changed_files(self) -> list[str]:
        return sorted({path for step in self.steps for path in step.changed})

    @property
    def tool_calls(self) -> Iterator[ToolCall]:
        return (step.tool for step in self.steps if step.tool)

    @property
    def started_at(self) -> str | None:
        first = self.ask or (self.steps[0] if self.steps else None)
        return first.at if first else None

    @property
    def label(self) -> str:
        """What the turn is called: the ask's first line, or what happened before any."""
        if self.ask:
            return next((line.strip() for line in self.ask.text.splitlines() if line.strip()), "")
        return self.events[0].text if self.events else "Before the first ask"


@dataclass(frozen=True, slots=True)
class AgentRun:
    """A subagent the assistant started: what it was asked, everything it did, and how it
    ended. Its own journal, kept apart from the session's so it never reads as yours."""

    id: str
    call_id: str  # the tool call that started it, in the session's entries
    kind: str  # "Explore", "general-purpose", or a custom agent's name
    description: str
    prompt: str
    entries: tuple[Entry, ...] = ()
    model: str = ""
    status: str = ""  # "completed", "failed", "killed"…; empty while nothing says
    report: str = ""  # its final words, what the assistant got back
    duration_ms: int | None = None
    tokens: int | None = None
    tool_uses: int | None = None
    background: bool = False

    @property
    def steps(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if not e.is_ask)

    @property
    def finished(self) -> bool:
        return self.status not in ("", "running", "async_launched")

    @property
    def failed(self) -> bool:
        return self.status in ("failed", "error", "killed")

    @property
    def state(self) -> Literal["done", "failed", "open"]:
        """How it ended, in one word: done, failed (or stopped), or open while nothing says."""
        return "failed" if self.failed else "done" if self.finished else "open"

    @property
    def last_at(self) -> datetime | None:
        """When its journal last recorded something."""
        return max((at for e in self.entries if (at := moment(e.at))), default=None)

    def is_running(self, now: datetime) -> bool:
        """Nothing says it ended, and its journal is still being written."""
        return not self.finished and is_recent(self.last_at, now)


@dataclass(frozen=True, slots=True)
class Session:
    """A session from any tool, in the shape the rest of the system relies on."""

    id: str
    provider: str
    project: Path
    entries: tuple[Entry, ...]
    title: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    agents: tuple[AgentRun, ...] = ()

    def agent(self, agent_id: str) -> AgentRun | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def agent_for(self, call_id: str) -> AgentRun | None:
        """The run a tool call started."""
        return next((a for a in self.agents if a.call_id == call_id), None) if call_id else None

    def agents_in(self, turn: Turn) -> list[AgentRun]:
        """The runs a turn's calls started, in the order it started them."""
        return [run for call in turn.tool_calls if (run := self.agent_for(call.id))]

    def spawned_in(self) -> dict[str, int]:
        """Agent id -> the turn whose call started it."""
        found: dict[str, int] = {}
        for turn in self.turns:
            for run in self.agents_in(turn):
                found.setdefault(run.id, turn.number)
        return found

    @property
    def start(self) -> datetime | None:
        return moment(self.started_at)

    @property
    def end(self) -> datetime | None:
        return moment(self.ended_at)

    @property
    def last_activity(self) -> datetime | None:
        """The last thing recorded anywhere in it: its own journal or a subagent's."""
        times = [self.end, *(run.last_at for run in self.agents)]
        return max((at for at in times if at), default=None)

    def is_live(self, now: datetime) -> bool:
        """Still being written: something was recorded in the last few minutes."""
        return is_recent(self.last_activity, now)

    def running_agents(self, now: datetime) -> list[AgentRun]:
        return [run for run in self.agents if run.is_running(now)]

    @property
    def wall_seconds(self) -> float:
        """From its first record to its last, breaks included."""
        return seconds_between(self.start, self.end)

    @property
    def asks(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.is_ask]

    @property
    def turns(self) -> list[Turn]:
        """The journal cut at each ask: every turn starts with what the human asked."""
        cuts = [i for i, entry in enumerate(self.entries) if entry.is_ask and i > 0]
        spans = pairwise([0, *cuts, len(self.entries)])
        chunks = [self.entries[start:end] for start, end in spans if end > start]
        return [Turn.from_entries(n, chunk) for n, chunk in enumerate(chunks, start=1)]

    @property
    def tool_calls(self) -> int:
        return sum(1 for entry in self.entries if entry.tool)

    def edits_by_file(self) -> dict[str, list[int]]:
        """Each file the assistant changed, with the turns that changed it, in the order
        the files were first changed."""
        found: dict[str, list[int]] = {}
        for turn in self.turns:
            for path in dict.fromkeys(p for step in turn.steps for p in step.changed):
                found.setdefault(path, []).append(turn.number)
        return found

    @property
    def headline(self) -> str:
        asks = self.asks
        return self.title or (asks[0].text if asks else self.id)

    @property
    def ref(self) -> SourceRef:
        return self.entries[0].ref

    @property
    def is_empty(self) -> bool:
        return not self.entries
