"""The work the assistant organised around itself: the checklist it kept (tasks) and the
helpers it sent off (subagents). Both used to be lines in the folded steps; here they get
places of their own: a card in the turn that started a helper, a tab in the index for each,
and a chip in a turn's margin for every task it moved."""

from dataclasses import dataclass, field
from datetime import datetime
from html import escape

from matters.clock import now
from matters.session import AgentRun, Session
from matters.tasks import ACTIVE, DONE, PENDING, Task
from matters.web.icons import icon
from matters.web.library import agent_href
from matters.web.markdown import render_markdown
from matters.web.text import count, milliseconds, model_name, plural

MAX_CHIPS = 4  # tasks named in a turn's margin before the rest are a count
SHORT_REPORT = 700  # characters: a report this short is shown open on its card

TICK = {PENDING: "○", ACTIVE: "◐", DONE: "✓"}
TASK_WORD = {PENDING: "to do", ACTIVE: "in progress", DONE: "done"}
MOVE_WORD = {PENDING: "added", ACTIVE: "started", DONE: "done"}
STATE_WORD = {"done": "done", "open": "stopped without a result", "running": "running"}


@dataclass(frozen=True)
class RunView:
    """A subagent's run as the pages show it, as of `at`: a run nothing says ended is
    running while its journal is still being written, and stopped once it is quiet."""

    session: Session
    run: AgentRun
    at: datetime = field(default_factory=now)

    @property
    def href(self) -> str:
        return agent_href(self.session, self.run.id)

    @property
    def state(self) -> str:
        return "running" if self.is_running else self.run.state

    @property
    def is_running(self) -> bool:
        return self.run.is_running(self.at)

    @property
    def word(self) -> str:
        """How it ended, in a word or two."""
        if self.run.failed:
            return "stopped" if self.run.status == "killed" else "failed"
        return STATE_WORD[self.state]

    @property
    def title(self) -> str:
        return self.run.description or self.run.kind

    @property
    def facts(self) -> list[str]:
        """What the run cost, as short phrases: model, time, tokens, tool calls."""
        run = self.run
        facts = []
        if run.model:
            facts.append(model_name(run.model))
        if run.duration_ms:
            facts.append(milliseconds(run.duration_ms))
        if run.tokens:
            facts.append(f"{count(run.tokens)} tokens")
        uses = run.tool_uses if run.tool_uses is not None else sum(1 for e in run.steps if e.tool)
        if uses or run.entries:
            facts.append(plural(uses, "tool call"))
        if run.background:
            facts.append("in the background")
        return facts

    def card(self) -> str:
        """The helper a turn sent off: who, what for, how it went, and what it said back,
        with the way into the whole run. Outside the folded steps, so it is seen."""
        run, link = self.run, escape(self.href)
        report = ""
        if run.report:
            body = render_markdown(run.report, self.session.project)
            opened = " open" if len(run.report) <= SHORT_REPORT else ""
            report = (
                f'<details class="agent-report"{opened}><summary>What it reported</summary>'
                f'<div class="md">{body}</div></details>'
            )
        facts = " · ".join(escape(f) for f in self.facts)
        return f"""<aside class="agent-run {self.state}" aria-label="Subagent: {escape(run.description)}">
  <p class="agent-head">{icon("agent")}<span>Subagent</span><span class="agent-kind">{escape(run.kind)}</span>
    <span class="agent-state">{escape(self.word)}</span></p>
  <div class="agent-body"><p class="agent-what"><a href="{link}" data-panel>{escape(self.title)}</a></p>
  <p class="agent-facts">{facts}</p>{report}
  <p class="agent-open"><a href="{link}" data-panel>Open the run: its prompt and every step</a></p></div></aside>"""

    def index_row(self, turn: int | None) -> str:
        """Its line in the index: kind, what for, the turn that started it, how it went."""
        run = self.run
        ref = f'<span class="turn-refs"><a href="#t{turn}">{turn}</a></span>' if turn else ""
        facts = " · ".join(escape(f) for f in [self.word, *self.facts[1:3]])
        words = f"{run.kind} {run.description}".lower()
        return (
            f'<li class="{self.state}" data-filter="{escape(words[:300])}"><div class="agent-row">'
            f'<a class="agent" href="{escape(self.href)}" data-panel>'
            f'<span class="agent-kind">{escape(run.kind)}</span>{escape(self.title)}</a>{ref}</div>'
            f'<p class="agent-facts">{facts}</p></li>'
        )


def task_row(task: Task, live: bool = False) -> str:
    """A task in the index: its tick, its subject, the turns that moved it. While the
    session is `live`, the task in progress is the one being worked on now."""
    status = f"{task.status} live" if live and task.status == ACTIVE else task.status
    tip = f' title="{escape(task.description[:400])}"' if task.description else ""
    refs = "".join(f"<a href=#t{n}>{n}</a>" for n in task.turns[-3:])
    return (
        f'<li id="task-{escape(task.id)}" class="task {status}" data-filter="{escape(task.subject.lower()[:300])}">'
        f'<span class="tick" title="{TASK_WORD.get(task.status, task.status)}">{TICK.get(task.status, "·")}</span>'
        f'<span class="task-subject"{tip}>{escape(task.subject)}</span>'
        f'<span class="turn-refs">{refs}</span></li>'
    )


def task_chips(moved: list[tuple[Task, str]]) -> str:
    """The tasks a turn moved, in its margin line: what it finished, started or added."""
    if not moved:
        return ""
    order = {DONE: 0, ACTIVE: 1, PENDING: 2}
    moved = sorted(moved, key=lambda m: order.get(m[1], 3))
    chips = "".join(
        f'<a class="task-chip {status}" href="#task-{escape(task.id)}" title="{MOVE_WORD.get(status, status)}: {escape(task.subject)}">'
        f"{TICK.get(status, '·')} {escape(task.subject)}</a>"
        for task, status in moved[:MAX_CHIPS]
    )
    if (rest := len(moved) - MAX_CHIPS) > 0:
        chips += f'<a class="task-chip more" href="#index-tasks">+{rest}</a>'
    return f'<div class="tasks-moved">{icon("tasks")}{chips}</div>'
