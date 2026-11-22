"""The assistant's task list, rebuilt from the calls that kept it.

Claude Code keeps a checklist while it works: TaskCreate adds a task, TaskUpdate moves it
(pending → in_progress → completed, or deleted). Older versions rewrote the whole list
with each TodoWrite instead. Either way, replaying the calls in order gives every task,
where it stands at the end, and the turns where it moved.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from matters.session import Session, ToolCall

PENDING, ACTIVE, DONE, DELETED = "pending", "in_progress", "completed", "deleted"
OPEN = frozenset({PENDING, ACTIVE})
TASK_TOOLS = frozenset({"TaskCreate", "TaskUpdate", "TodoWrite"})


@dataclass(slots=True)
class Task:
    id: str
    subject: str
    description: str = ""
    status: str = PENDING
    moves: list[tuple[int, str]] = field(default_factory=list)  # (turn, status it moved to)

    @classmethod
    def made(cls, turn: int, task_id: str, subject: str, description: str = "") -> "Task":
        """A task as it was added: pending, in the turn that added it."""
        return cls(task_id, subject, description, moves=[(turn, PENDING)])

    @property
    def is_open(self) -> bool:
        return self.status in OPEN

    @property
    def is_done(self) -> bool:
        return self.status == DONE

    @property
    def turns(self) -> list[int]:
        return sorted({turn for turn, _ in self.moves})

    def move(self, turn: int, status: str) -> None:
        if status != self.status:
            self.status = status
            self.moves.append((turn, status))

    def last_move_in(self, turn: int) -> str | None:
        """The status a turn last moved this task to, if it moved it."""
        return next((status for n, status in reversed(self.moves) if n == turn), None)


@dataclass(frozen=True, slots=True)
class TaskList:
    """Every task the session's assistant kept, in the order they were made. Deleted tasks
    are left out: the assistant took them back."""

    tasks: tuple[Task, ...] = ()

    @classmethod
    def from_session(cls, session: Session) -> "TaskList":
        replay = _Replay()
        for turn in session.turns:
            for call in turn.tool_calls:
                if call.name in TASK_TOOLS and not call.is_error:
                    replay.apply(turn.number, call)
        return cls(tuple(t for t in replay.tasks.values() if t.status != DELETED))

    def __iter__(self) -> Iterator[Task]:
        return iter(self.tasks)

    def __len__(self) -> int:
        return len(self.tasks)

    @property
    def done(self) -> int:
        return sum(1 for t in self.tasks if t.is_done)

    @property
    def unfinished(self) -> int:
        return sum(1 for t in self.tasks if t.is_open)

    def moved_in(self, turn: int) -> list[tuple[Task, str]]:
        """The tasks a turn moved, each with the last status it moved them to."""
        return [(t, status) for t in self.tasks if (status := t.last_move_in(turn))]


class _Replay:
    """The list as the calls leave it, one call at a time."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def apply(self, turn: int, call: ToolCall) -> None:
        match call.name:
            case "TaskCreate":
                self.create(turn, call)
            case "TaskUpdate":
                self.update(turn, call.input)
            case "TodoWrite":
                self.rewrite(turn, call.input.get("todos"))

    def create(self, turn: int, call: ToolCall) -> None:
        found = call.outcome.get("task")
        made: dict[str, Any] = found if isinstance(found, dict) else {}
        task_id = str(made.get("id") or _number_in(call.result or "") or len(self.tasks) + 1)
        subject = str(call.input.get("subject") or made.get("subject") or f"Task {task_id}")
        description = str(call.input.get("description") or "")
        self.tasks[task_id] = Task.made(turn, task_id, subject, description)

    def update(self, turn: int, given: dict[str, Any]) -> None:
        task_id = str(given.get("taskId") or given.get("id") or "")
        if task_id not in self.tasks:  # made before this journal begins, or by another agent
            self.tasks[task_id] = Task(task_id, str(given.get("subject") or f"Task {task_id}"))
        task = self.tasks[task_id]
        task.subject = str(given.get("subject") or task.subject)
        task.description = str(given.get("description") or task.description)
        if status := given.get("status"):
            task.move(turn, str(status))

    def rewrite(self, turn: int, todos: Any) -> None:
        """TodoWrite: the whole list each time. A task is its text; one that is missing from
        the new list was dropped."""
        if not isinstance(todos, list):
            return
        seen = set()
        for todo in todos:
            if not isinstance(todo, dict) or not todo.get("content"):
                continue
            key = str(todo.get("id") or todo["content"])
            seen.add(key)
            if key not in self.tasks:
                self.tasks[key] = Task.made(turn, key, str(todo["content"]))
            self.tasks[key].move(turn, str(todo.get("status") or PENDING))
        for key, task in self.tasks.items():
            if key not in seen:
                task.move(turn, DELETED)


def _number_in(text: str) -> str:
    """'Task #3 created successfully' -> '3'."""
    found = re.search(r"#(\d+)", text)
    return found.group(1) if found else ""
