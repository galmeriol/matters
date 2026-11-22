"""One line of a Claude Code journal, and the entries it becomes.

A record is a JSON object: a user message (an ask, a command, a tool's result), an
assistant message (text, thinking, tool calls), or something the CLI noted (a title, a
message queued while the assistant worked). `Record` reads the raw shape; nothing past
this module and its neighbours knows it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from matters.clock import moment
from matters.jsonl import json_lines
from matters.session import AgentRun, Entry, Part, Session, SourceRef, Tokens, ToolCall
from matters.sources import claude_tags

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
COMPACTED = "Context compacted: Claude Code summarised the work so far"


@dataclass(frozen=True, slots=True)
class Record:
    data: dict[str, Any]
    ref: SourceRef

    @classmethod
    def read_all(cls, path: Path) -> list["Record"]:
        return [cls(data, SourceRef(path, line)) for line, data in json_lines(path)]

    @property
    def type(self) -> str | None:
        return self.data.get("type")

    @property
    def timestamp(self) -> str | None:
        return self.data.get("timestamp")

    @property
    def is_sidechain(self) -> bool:
        """Written by a subagent rather than the session's own assistant."""
        return bool(self.data.get("isSidechain"))

    @property
    def message(self) -> dict[str, Any]:
        return self.data.get("message") or {}

    @property
    def content(self) -> Any:
        return self.message.get("content")

    def blocks(self, kind: str) -> list[dict[str, Any]]:
        return blocks(self.content, kind)

    @property
    def texts(self) -> list[str]:
        """Its words: the whole content when that is a string, else each text block."""
        return texts(self.content)

    @property
    def model_call(self) -> tuple[str, Tokens] | None:
        """An assistant record's model call and its usage. One call is written as several
        records (one per content block), each repeating the same usage: count it once."""
        usage = self.message.get("usage")
        if self.type != "assistant" or not self.message.get("id") or not isinstance(usage, dict):
            return None
        return str(self.message["id"]), Tokens.from_usage(usage)

    def entries(self, results: "Results") -> list[Entry]:
        """What this record adds to the journal, each stamped with when it was written."""
        match self.type:
            case "user":
                found = self._human()
            case "assistant":
                found = self._steps(results)
            case "attachment":
                found = self._queued()
            case _:
                found = []
        return [replace(entry, at=self.timestamp) for entry in found]

    def _human(self) -> list[Entry]:
        """An ask, a command, its output, an interruption, or a notice."""
        if "toolUseResult" in self.data or self.data.get("isMeta"):
            return []
        whole = "\n".join(self.texts)
        if (command := claude_tags.command(whole)) is not None:
            return [
                Entry(
                    "command", command, self.ref, parts=_output(claude_tags.command_output(whole))
                )
            ]
        if (output := claude_tags.command_output(whole)) is not None:
            return [Entry("command", "", self.ref, parts=_output(output))]
        if whole.strip().startswith("[Request interrupted"):
            return [Entry("interrupt", "Interrupted", self.ref)]
        if self.data.get("isCompactSummary"):
            # Claude Code's own summary of the work so far, written when the context filled
            # up: not something the human asked, though it quotes them at length.
            summary = Part("reminder", text=whole, label=COMPACTED)
            return [Entry("notice", COMPACTED, self.ref, parts=(summary,))]
        images = [image for block in self.blocks("image") if (image := _image(block))]
        has_images = bool(self.blocks("image"))
        parts = [
            p for text in self.texts for p in claude_tags.message_parts(text, has_images=has_images)
        ]
        parts += images
        if any(part.kind in claude_tags.TYPED for part in parts):
            return [Entry("ask", claude_tags.ask_text(parts), self.ref, parts=tuple(parts))]
        if parts:
            return [Entry("notice", parts[0].label, self.ref, parts=tuple(parts))]
        return []

    def _queued(self) -> list[Entry]:
        """A message the human sent while the assistant was still working."""
        attachment = self.data.get("attachment") or {}
        if attachment.get("type") != "queued_command":
            return []
        words = texts(attachment.get("prompt"))
        parts = [p for text in words for p in claude_tags.message_parts(text, has_images=False)]
        if not any(part.kind in claude_tags.TYPED for part in parts):
            return []
        queued = Part("queued", label="Sent while Claude was working")
        return [Entry("ask", claude_tags.ask_text(parts), self.ref, parts=(queued, *parts))]

    def _steps(self, results: "Results") -> list[Entry]:
        content = self.content
        steps: list[Entry] = []
        for block in content if isinstance(content, list) else [{"type": "text", "text": content}]:
            if not isinstance(block, dict):
                continue
            match block.get("type"):
                case "text" if words := str(block.get("text", "")).strip():
                    steps.append(Entry("text", words, self.ref))
                case "thinking" if words := str(block.get("thinking", "")).strip():
                    steps.append(Entry("thinking", words, self.ref))
                case "tool_use":
                    call = results.answer(str(block.get("id") or "")).to_call(block)
                    steps.append(Entry("tool", "", self.ref, call))
        return steps


@dataclass(frozen=True, slots=True)
class Journal:
    """The entries of one journal file, the session's own or (sidechain) a subagent's,
    with what the file says about itself."""

    records: tuple[Record, ...] = ()
    entries: tuple[Entry, ...] = ()
    stamps: tuple[str, ...] = ()  # when each record that added entries was written
    title: str | None = None
    cwd: str | None = None

    @classmethod
    def read(cls, path: Path, *, sidechain: bool = False) -> "Journal":
        records = Record.read_all(path)
        results = Results.from_records(records)
        title = cwd = None
        stamps: list[str] = []
        entries: list[Entry] = []
        calls: dict[str, tuple[int, Tokens]] = {}  # model call id -> (its first entry, usage)
        for record in records:
            if record.type == "ai-title":
                title = record.data.get("aiTitle") or title
            cwd = cwd or record.data.get("cwd")
            new = record.entries(results) if record.is_sidechain == sidechain else []
            if new and record.timestamp:
                stamps.append(record.timestamp)
            if new and (call := record.model_call):
                call_id, tokens = call
                first = calls[call_id][0] if call_id in calls else len(entries)
                calls[call_id] = (first, tokens)  # the last record of a call has its final usage
            for entry in new:
                _append(entries, entry)
        for first, tokens in calls.values():
            if first < len(entries):
                entries[first] = replace(entries[first], tokens=tokens)
        return cls(tuple(records), tuple(entries), tuple(stamps), title, cwd)

    def to_session(self, path: Path, agents: tuple[AgentRun, ...] = ()) -> Session:
        return Session(
            id=path.stem,
            provider="claude-code",
            project=Path(self.cwd) if self.cwd else _project_from_folder(path.parent.name),
            entries=self.entries,
            title=self.title,
            started_at=self.stamps[0] if self.stamps else None,
            ended_at=self.stamps[-1] if self.stamps else None,
            agents=agents,
        )

    def calls_to(self, tools: frozenset[str]) -> list[ToolCall]:
        return [e.tool for e in self.entries if e.tool and e.tool.name in tools]

    @property
    def steps(self) -> list[Entry]:
        return [e for e in self.entries if not e.is_ask]

    @property
    def tool_calls(self) -> int:
        return sum(1 for e in self.steps if e.tool)

    @property
    def prompt(self) -> str:
        """What it was first asked: a subagent's journal opens with its prompt."""
        return self.entries[0].text if self.entries and self.entries[0].is_ask else ""

    @property
    def last_words(self) -> str:
        return next((e.text for e in reversed(self.steps) if e.kind == "text"), "")

    @property
    def elapsed_ms(self) -> int | None:
        if len(self.stamps) < 2:
            return None
        start, end = moment(self.stamps[0]), moment(self.stamps[-1])
        return max(0, round((end - start).total_seconds() * 1000)) if start and end else None


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What came back for one tool call, from a later user record."""

    text: str | None = None
    is_error: bool = False
    at: str | None = None
    outcome: dict[str, Any] = field(default_factory=dict)  # the result as structured data

    def to_call(self, use: Mapping[str, Any]) -> ToolCall:
        """The call a tool_use block made, paired with this result."""
        return ToolCall(
            str(use.get("name")),
            use.get("input") or {},
            self.text,
            self.is_error,
            self.at,
            id=str(use.get("id") or ""),
            outcome=self.outcome,
        )


NO_RESULT = ToolResult()


class Results(dict[str, ToolResult]):
    """Every tool result in a journal, by the id of the call it answers."""

    @classmethod
    def from_records(cls, records: list[Record]) -> "Results":
        results = cls()
        for record in records:
            if record.type != "user":
                continue
            answers = [b for b in record.blocks("tool_result") if b.get("tool_use_id")]
            # the structured result belongs to the record: it is only safe with one answer
            structured = record.data.get("toolUseResult")
            outcome = structured if isinstance(structured, dict) and len(answers) == 1 else {}
            for block in answers:
                results[str(block["tool_use_id"])] = ToolResult(
                    text(block.get("content")),
                    bool(block.get("is_error")),
                    record.timestamp,
                    outcome,
                )
        return results

    def answer(self, call_id: str) -> ToolResult:
        return self.get(call_id, NO_RESULT)


def blocks(content: Any, kind: str) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and block.get("type") == kind]


def texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [str(block.get("text", "")) for block in blocks(content, "text")]


def text(content: Any) -> str:
    """Content as one string: a tool result, or a subagent's report."""
    if content is None:
        return ""
    return content.strip() if isinstance(content, str) else "\n".join(texts(content)).strip()


def _append(entries: list[Entry], entry: Entry) -> None:
    """Command output arrives in its own record: attach it to the command it belongs to."""
    is_output_only = entry.kind == "command" and not entry.text
    if is_output_only and entries and entries[-1].kind == "command":
        entries[-1] = replace(entries[-1], parts=entries[-1].parts + entry.parts)
    elif is_output_only:
        entries.append(replace(entry, text="Command output"))
    else:
        entries.append(entry)


def _project_from_folder(name: str) -> Path:
    """Lossy fallback when no record names its cwd: every "-" was some separator."""
    return Path(name.replace("-", "/"))


def _output(output: str | None) -> tuple[Part, ...]:
    return (Part("output", output),) if output else ()


def _image(block: dict[str, Any]) -> Part | None:
    source = block.get("source") or {}
    media_type, data = source.get("media_type"), source.get("data")
    if source.get("type") != "base64" or media_type not in IMAGE_TYPES or not data:
        return None
    return Part("image", str(data), "Image", str(media_type))
