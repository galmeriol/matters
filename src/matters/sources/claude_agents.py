"""Subagents, pieced together from the three places Claude Code leaves them.

The call that started one is in the session's journal. A run in the background reports
how it ended in a `<task-notification>` the session receives later. And each subagent
keeps its own journal, `<session>/subagents/agent-<id>.jsonl`, with a `.meta.json`
beside it: its type, description, model, and the call that started it.
"""

import contextlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from matters.session import AgentRun, ToolCall
from matters.sources import claude_tags
from matters.sources.claude_records import Journal, Record, text

AGENT_TOOLS = frozenset({"Agent", "Task"})  # "Task" is the agent tool's older name
UNSETTLED = ("", "async_launched")  # a status that doesn't say how the run ended

type Notice = dict[str, str]


def folder_of(session_file: Path) -> Path:
    """<session id>/subagents, beside the session's own file."""
    return session_file.with_suffix("") / "subagents"


def last_changed(session_file: Path) -> tuple[int, ...]:
    """When a session last changed: its file, and its subagents' (a running agent grows)."""
    folder = folder_of(session_file)
    subagents = sorted(p.stat().st_mtime_ns for p in folder.iterdir()) if folder.is_dir() else []
    return (session_file.stat().st_mtime_ns, *subagents)


class Notices(dict[str, Notice]):
    """Background-task notices by the call and the task they are about. A resumed agent
    notices again; the last one says how it stands."""

    @classmethod
    def from_records(cls, records: list[Record]) -> "Notices":
        found = cls()
        for record in records:
            if record.type != "user":
                continue
            for fields in (f for words in record.texts for f in claude_tags.notifications(words)):
                found.update(
                    (key, fields)
                    for key in (fields.get("tool-use-id"), fields.get("task-id"))
                    if key
                )
        return found

    def about(self, *keys: str) -> Notice:
        return next((self[key] for key in keys if key in self), {})


@dataclass(frozen=True)
class AgentFile:
    """A subagent's own journal and the meta file beside it."""

    path: Path

    @classmethod
    def all_beside(cls, session_file: Path) -> list["AgentFile"]:
        return [cls(f) for f in sorted(folder_of(session_file).glob("agent-*.jsonl"))]

    @property
    def agent_id(self) -> str:
        return self.path.stem.removeprefix("agent-")

    @cached_property
    def meta(self) -> dict[str, Any]:
        with contextlib.suppress(ValueError, OSError):
            loaded = json.loads(self.path.with_suffix(".meta.json").read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        return {}

    def started_by(self, call: ToolCall) -> bool:
        return self.meta.get("toolUseId") == call.id

    def read(self) -> Journal:
        return Journal.read(self.path, sidechain=True)


@dataclass(frozen=True)
class Evidence:
    """Everything known about one run. Each figure is taken from the most direct witness
    that has it: the notice, then the call's result, then the meta file and transcript."""

    agent_id: str
    call: ToolCall | None
    file: AgentFile | None
    notice: Notice = field(default_factory=dict)

    @classmethod
    def for_call(cls, call: ToolCall, file: AgentFile | None, notices: Notices) -> "Evidence":
        agent_id = file.agent_id if file else str(call.outcome.get("agentId") or call.id)
        return cls(agent_id, call, file, notices.about(call.id, agent_id))

    @classmethod
    def for_file(cls, file: AgentFile, notices: Notices) -> "Evidence":
        """A transcript whose call the session's journal doesn't hold."""
        return cls(file.agent_id, None, file, notices.about(file.agent_id))

    @property
    def given(self) -> dict[str, Any]:
        return self.call.input if self.call else {}

    @property
    def outcome(self) -> dict[str, Any]:
        return self.call.outcome if self.call else {}

    @property
    def meta(self) -> dict[str, Any]:
        return self.file.meta if self.file else {}

    @cached_property
    def journal(self) -> Journal:
        return self.file.read() if self.file else Journal()

    def to_run(self) -> AgentRun:
        return AgentRun(
            id=self.agent_id,
            call_id=self.call.id if self.call else str(self.meta.get("toolUseId") or ""),
            kind=str(self.meta.get("agentType") or self.given.get("subagent_type") or "agent"),
            description=str(self.meta.get("description") or self.given.get("description") or ""),
            prompt=self.prompt,
            entries=self.journal.entries,
            model=str(self.meta.get("model") or self.outcome.get("resolvedModel") or ""),
            status=self.status,
            report=self.report,
            duration_ms=_number(
                self.notice.get("duration_ms"),
                self.outcome.get("totalDurationMs"),
                self.journal.elapsed_ms,
            ),
            tokens=self.tokens,
            tool_uses=_number(
                self.notice.get("tool_uses"),
                self.outcome.get("totalToolUseCount"),
                self.journal.tool_calls if self.file else None,
            ),
            background=bool(self.outcome.get("isAsync") or self.given.get("run_in_background")),
        )

    @property
    def prompt(self) -> str:
        given = self.given.get("prompt") or self.outcome.get("prompt")
        return str(given) if given else self.journal.prompt

    @property
    def status(self) -> str:
        status = self.notice.get("status") or str(self.outcome.get("status") or "")
        if status in UNSETTLED and self.meta.get("finished"):
            status = "completed"
        if status in UNSETTLED and self.call and self.call.is_error:
            status = "failed"
        if not status and self.call and self.call.result is not None:
            status = "completed"  # an older run: its result came back, so it finished
        return status

    @property
    def report(self) -> str:
        if found := self.notice.get("result") or text(self.outcome.get("content")):
            return found
        if self.journal.last_words:
            return self.journal.last_words
        if self.call and not self.outcome.get("isAsync"):
            return self.call.result or ""  # an older run: its report was the call's result
        return ""

    @property
    def tokens(self) -> int | None:
        found = _number(self.notice.get("subagent_tokens"), self.outcome.get("totalTokens"))
        if found is None and self.journal.steps:
            return sum(e.tokens.total for e in self.journal.steps if e.tokens) or None
        return found


def runs(calls: list[ToolCall], files: list[AgentFile], notices: Notices) -> Iterator[AgentRun]:
    """Every subagent the session started, in the order it started them; then any
    transcript whose call the journal doesn't hold."""
    unclaimed = {f.agent_id: f for f in files}
    for call in calls:
        yield Evidence.for_call(call, _claim(unclaimed, call), notices).to_run()
    for file in unclaimed.values():
        yield Evidence.for_file(file, notices).to_run()


def _claim(unclaimed: dict[str, AgentFile], call: ToolCall) -> AgentFile | None:
    """The transcript a call started: named in its result, or (older runs) in the meta."""
    agent_id = str(call.outcome.get("agentId") or "")
    if agent_id not in unclaimed:
        agent_id = next((f.agent_id for f in unclaimed.values() if f.started_by(call)), "")
    return unclaimed.pop(agent_id, None)


def _number(*candidates: Any) -> int | None:
    """The first candidate that reads as a whole number."""
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    return None
