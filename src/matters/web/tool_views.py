"""How each kind of tool call reads on a page.

Role: ToolView. summary() is a one-line plain-text label, body() is HTML.
The factory picks a view by tool name. Unknown tools get the generic view,
so a new tool never breaks the page; it just looks plainer until it gets
its own view.
"""

import difflib
import json
from html import escape
from pathlib import Path
from typing import Any, ClassVar

from matters.session import Entry, ToolCall
from matters.web.human import source
from matters.web.markdown import render_markdown
from matters.web.text import clip, first_line

CLIP = 6000


class ToolView:
    names: ClassVar[tuple[str, ...]] = ()
    _registry: ClassVar[dict[str, type["ToolView"]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in cls.names:
            ToolView._registry[name] = cls

    @staticmethod
    def for_(tool: ToolCall, project: Path) -> "ToolView":
        return ToolView._registry.get(tool.name, ToolView)(tool, project)

    def __init__(self, tool: ToolCall, project: Path) -> None:
        self.tool = tool
        self.project = project

    def summary(self) -> str:
        return next(
            (v for v in self.tool.input.values() if isinstance(v, str) and 0 < len(v) < 200),
            "",
        )

    def body(self) -> str:
        return (
            _pre(json.dumps(self.tool.input, indent=2, ensure_ascii=False), "input") + self.result()
        )

    def result(self) -> str:
        if self.tool.result is None:
            return '<p class="muted">No result recorded.</p>'
        return _pre(self.tool.result, "result error" if self.tool.is_error else "result")

    def input(self, key: str) -> str:
        return str(self.tool.input.get(key) or "")

    def relative(self, path: str) -> str:
        return path.removeprefix(f"{self.project}/")


class BashView(ToolView):
    names: ClassVar[tuple[str, ...]] = ("Bash",)

    def summary(self) -> str:
        return self.input("description") or self.input("command").split("\n")[0]

    def body(self) -> str:
        return _pre(f"$ {self.input('command')}", "input") + self.result()


class FileView(ToolView):
    names: ClassVar[tuple[str, ...]] = ("Read", "NotebookRead")

    def summary(self) -> str:
        return self.relative(self.input("file_path") or self.input("notebook_path"))

    def body(self) -> str:
        return self.result()


class EditView(FileView):
    names: ClassVar[tuple[str, ...]] = ("Edit",)

    def body(self) -> str:
        return diff(self.input("old_string"), self.input("new_string")) + self.error()

    def error(self) -> str:
        return self.result() if self.tool.is_error else ""


class MultiEditView(EditView):
    names: ClassVar[tuple[str, ...]] = ("MultiEdit",)

    def body(self) -> str:
        edits = self.tool.input.get("edits") or []
        diffs = (diff(str(e.get("old_string", "")), str(e.get("new_string", ""))) for e in edits)
        return "".join(diffs) + self.error()


class WriteView(EditView):
    names: ClassVar[tuple[str, ...]] = ("Write",)

    def body(self) -> str:
        return diff("", self.input("content")) + self.error()


class SearchView(ToolView):
    names: ClassVar[tuple[str, ...]] = ("Grep", "Glob")

    def summary(self) -> str:
        where = self.relative(self.input("path"))
        return f"{self.input('pattern')}  in {where}" if where else self.input("pattern")


class WebView(ToolView):
    names: ClassVar[tuple[str, ...]] = ("WebFetch", "WebSearch")

    def summary(self) -> str:
        return self.input("url") or self.input("query")


class AgentView(ToolView):
    """Starting a subagent. Its run has a card of its own in the turn; here, the brief."""

    names: ClassVar[tuple[str, ...]] = ("Task", "Agent")

    def summary(self) -> str:
        kind = self.input("subagent_type")
        return f"{kind}: {self.input('description')}" if kind else self.input("description")

    def body(self) -> str:
        return _pre(self.input("prompt"), "input") + self.result()


class TaskView(ToolView):
    """The assistant's checklist: a task added, or moved to a new state."""

    names: ClassVar[tuple[str, ...]] = ("TaskCreate", "TaskUpdate", "TaskGet", "TaskStop")

    def summary(self) -> str:
        task_id = self.input("taskId") or self.input("task_id")
        status = self.input("status").replace("_", " ")
        subject = self.input("subject")
        if self.tool.name == "TaskCreate":
            return f"Added: {subject}"
        if self.tool.name == "TaskUpdate":
            what = subject or f"#{task_id}"
            return f"{what} → {status}" if status else f"Changed {what}"
        return f"#{task_id}" if task_id else super().summary()

    def body(self) -> str:
        description = self.input("description")
        said = f'<p class="task-said">{escape(description)}</p>' if description else ""
        return said + self.result()


class TodoView(ToolView):
    """Older Claude Code: the whole checklist rewritten each time."""

    names: ClassVar[tuple[str, ...]] = ("TodoWrite",)
    TICKS: ClassVar[dict[str, str]] = {"completed": "✓", "in_progress": "◐", "pending": "○"}

    def todos(self) -> list[dict[str, Any]]:
        todos = self.tool.input.get("todos")
        return [t for t in todos if isinstance(t, dict)] if isinstance(todos, list) else []

    def summary(self) -> str:
        todos = self.todos()
        done = sum(1 for t in todos if t.get("status") == "completed")
        active = next((t for t in todos if t.get("status") == "in_progress"), None)
        now = f" · now: {active.get('activeForm') or active.get('content')}" if active else ""
        return f"{done}/{len(todos)} done{now}"

    def body(self) -> str:
        rows = "".join(
            f'<li class="task {escape(str(t.get("status", "")))}"><span class="tick">'
            f"{self.TICKS.get(str(t.get('status')), '·')}</span>"
            f'<span class="task-subject">{escape(str(t.get("content", "")))}</span></li>'
            for t in self.todos()
        )
        return f'<ol class="task-list">{rows}</ol>'


def _pre(text: str, css: str) -> str:
    shown = text[:CLIP]
    more = len(text) - len(shown)
    note = f'<p class="muted">… {more:,} more characters in the source.</p>' if more > 0 else ""
    return f'<pre class="{css}">{escape(shown)}</pre>{note}'


def diff(old: str, new: str) -> str:
    """A unified diff in the page's ink; with no old text, every line an addition."""
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2))[2:]
    if not old:
        lines = [f"+{line}" for line in new.splitlines()]
    shown = lines[:400]
    rows = "".join(f'<span class="{_diff_class(line)}">{escape(line)}</span>' for line in shown)
    more = len(lines) - len(shown)
    note = f'<p class="muted">… {more:,} more lines in the source.</p>' if more > 0 else ""
    return f'<pre class="diff">{rows}</pre>{note}'


def _diff_class(line: str) -> str:
    return {"+": "add", "-": "del", "@": "hunk"}.get(line[:1], "ctx")


def step_html(step: Entry, project: Path) -> str:
    """One step of work: a tool call (folded, its view inside), thinking, or a note."""
    if step.tool:
        view = ToolView.for_(step.tool, project)
        failed = " failed" if step.tool.is_error else ""
        return f"""<li><details class="tool{failed}"><summary><b>{escape(step.tool.name)}</b>
  <span class="target">{escape(clip(first_line(view.summary()), 140))}</span>{source(step)}</summary>
  {view.body()}</details></li>"""
    if step.kind == "thinking":
        return f"""<li><details class="thinking"><summary>Thinking{source(step)}</summary>
  <div class="md">{render_markdown(step.text, project)}</div></details></li>"""
    return f'<li class="note">{source(step)}<div class="md">{render_markdown(step.text, project)}</div></li>'
