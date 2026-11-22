"""The session page: what was asked and done, turn by turn, with the session's figures above
and an index beside it.

Pages link across each other wherever two things are the same thing seen twice: a
project's name opens its brief, a turn shows the knowledge it became, a file lists the
turns that edited it, a search hit opens its turn with the words marked."""

import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from html import escape
from pathlib import Path
from urllib.parse import quote

from matters.brief import Loose
from matters.changes import Change
from matters.clock import moment, now
from matters.knowledge.model import GLOBAL, Item, scope_name
from matters.links import editor_url
from matters.session import Session, Turn
from matters.tasks import TaskList
from matters.timeline import Timeline
from matters.web.frame import layout, rail
from matters.web.human import ask_html, event_html, source
from matters.web.icons import icon
from matters.web.library import Library, file_href, href, knowledge_href, project_href
from matters.web.markdown import render_markdown
from matters.web.orders import NEWEST, OLDEST, ORDERS
from matters.web.text import (
    ago,
    breakable,
    clip,
    count,
    duration,
    first_line,
    plural,
    span,
    unbroken,
)
from matters.web.timeline_view import TimelineView
from matters.web.tool_views import step_html
from matters.web.work_views import RunView, task_chips, task_row

OPEN_HEAD = 3  # turns left open in a long session, at the end it is read from
CHAPTER = 10  # turns per folded chapter after them
LONG_SESSION = 8  # turns: past this, everything after the first turns folds
MAX_REFS = 4  # turn numbers listed beside a file; the rest are in its stack
MAX_META_FILES = 6  # files named in a turn's margin line before the rest fold

ENDED = {
    "question": "waiting on you. The assistant's last words were a question",
    "failing": "with a check still failing",
    "unanswered": "with your last ask unanswered",
    "interrupted": "interrupted by you",
}

INDEX_TOOLS = (
    '<div class="index-tools" hidden><div class="index-tabs" role="tablist"></div>'
    '<input type="search" class="index-filter" placeholder="Filter the index" aria-label="Filter the index">'
    '<button type="button" class="unfold-all" hidden>Unfold all turns</button></div>'
)
TASK_KEY = (
    '<p class="task-key quiet">✓ done · ◐ in progress · ○ to do. '
    "The numbers are the turns that moved each one.</p>"
)


def session_page(
    library: Library,
    session: Session,
    view: TimelineView | None = None,
    at: datetime | None = None,
    newest_first: bool = False,
) -> str:
    """The page as of `at` (now): a session still being written says so. Its turns read
    from the first, or from the newest."""
    view = view or TimelineView("", {}, {})
    return SessionPage(library, session, view, at or now(), newest_first).to_html()


@dataclass
class SessionPage:
    library: Library
    session: Session
    view: TimelineView
    at: datetime
    newest_first: bool = False

    @cached_property
    def live(self) -> bool:
        return self.session.is_live(self.at)

    @cached_property
    def turns(self) -> list[Turn]:
        return self.session.turns

    @cached_property
    def learned(self) -> dict[int, list[Item]]:
        """Turn number -> the knowledge drawn from it."""
        return self.library.learned_in(self.session.id)

    @cached_property
    def edited(self) -> dict[str, list[int]]:
        return self.session.edits_by_file()

    @cached_property
    def tasks(self) -> TaskList:
        return TaskList.from_session(self.session)

    @property
    def line(self) -> Timeline | None:
        return self.view.line

    def relative(self, path: str) -> str:
        return path.removeprefix(f"{self.session.project}/")

    def to_html(self) -> str:
        session = self.session
        main = f"""<div class="session-page">
<header class="masthead">
  <p class="kicker"><a class="project-link" href="{escape(project_href(session.project))}" title="{escape(str(session.project))}">{escape(session.project.name or str(session.project))}</a>
    <span>{span(session.start, session.end)}</span></p>
  <h1>{escape(clip(first_line(session.headline), 140))}</h1>
  {self.ended()}
  {self.resume()}
  {self.glance()}
</header>
{self.view.section}
<div class="reading">
  <article class="turns" data-order="{self.order}" data-newest="{self.newest}">{self.chapters()}{self.to_newest()}</article>
  {self.index()}
</div>
</div>"""
        return layout(session.headline, rail(self.library, f"/s/{session.id}", session), main)

    def resume(self) -> str:
        session = self.session
        command = f"cd {shlex.quote(str(session.project))} && claude --resume {session.id}"
        return f"""<p class="resume"><button type="button" data-copy="{escape(command)}">Copy resume command</button>
    <code title="{escape(command)}">{escape(command)}</code>
    <a href="{escape(editor_url(session.ref))}">Open raw</a>
    <a href="{escape(href("/knowledge/pick", s=session.id))}">{icon("bulb")}Extract knowledge</a></p>"""

    def ended(self) -> str:
        """How the session ended, in words, with the way to its last turn, and the tasks
        the assistant never marked done."""
        if not (last := len(self.turns)):
            return ""
        if self.live:
            return self.running(last)
        unfinished = self.tasks.unfinished
        left = (
            f' <a class="open-tasks" href="#index-tasks">{plural(unfinished, "task")} '
            f"never marked done</a>"
            if unfinished
            else ""
        )
        if (loose := Loose.of(self.session)) is None:
            said = "with an answer, but" if unfinished else "with an answer; nothing was left open."
            return (
                f'<p class="ended"><b>Ended</b>{said}{left} <a href="#t{last}">Turn {last}</a></p>'
            )
        quoted = clip(first_line(loose.text), 160)
        return (
            f'<p class="ended open"><b>Ended</b><span class="loose" aria-hidden="true"></span>{ENDED[loose.ending]}: '
            f'<q>{escape(quoted)}</q> <a href="#t{loose.turn}">Turn {loose.turn}</a>{" ·" + left if left else ""}</p>'
        )

    def running(self, last: int) -> str:
        """A session still being written: when it last moved and the helpers still at
        work. The way to load what came since sits above the turns."""
        session, latest = self.session, self.session.last_activity
        quiet = (self.at - latest).total_seconds() if latest else 0
        helpers = len(session.running_agents(self.at))
        busy = (
            f' · <a href="#index-agents">{plural(helpers, "subagent")} at work</a>'
            if helpers
            else ""
        )
        return (
            f'<p class="ended live"><b>Running</b><span class="pulse" aria-hidden="true"></span>'
            f'Still being written · last activity <time class="ago" datetime="{latest.isoformat() if latest else ""}">{ago(quiet)}</time>{busy}'
            f' · <a href="#t{last}">Turn {last}</a></p>'
        )

    def glance(self) -> str:
        """The session's figures, each labelled, said in words, and a link to where it is
        taken apart: time to the lanes, asks and files to the index, knowledge to review."""
        cells = "".join(figure.to_html() for figure in Glance(self).figures())
        return f'<nav class="glance" aria-label="At a glance">{cells}</nav>'

    @property
    def order(self) -> str:
        return NEWEST if self.newest_first else OLDEST

    @property
    def newest(self) -> int:
        """The newest turn's number; 0 for a session without one."""
        return self.turns[-1].number if self.turns else 0

    def in_order(self, items: list[str]) -> list[str]:
        """Items kept in the order of the turns, put in the order they are read."""
        return items[::-1] if self.newest_first else items

    def turn_bar(self) -> str:
        """Above the turns: the way to load what came since, while the session is still
        being written (the page is a snapshot until then), and the order they read in."""
        refresh = (
            f'<a class="refresh" href="/s/{quote(self.session.id)}" data-refresh '
            f'title="Load what was written since">{icon("refresh")}Refresh</a>'
            if self.live
            else ""
        )
        bar = refresh + self.order_switch()
        return f'<div class="turn-bar">{bar}</div>' if bar else ""

    def order_switch(self) -> str:
        """Read this session from its first turn or its newest; kept for this session."""
        if len(self.turns) < 2:
            return ""
        here = f"/s/{quote(self.session.id)}"
        links = "".join(
            f'<a class="on" href="{here}?order={value}" aria-current="true" title="{name}">{value.title()}</a>'
            if value == self.order
            else f'<a href="{here}?order={value}" title="{name}">{value.title()}</a>'
            for value, name in ORDERS
        )
        tip = "Kept for this session. The order for every session is in the sliders menu."
        return f'<nav class="turn-order" aria-label="Order of this session\'s turns" title="{tip}">{links}</nav>'

    def to_newest(self) -> str:
        """A way to the newest turn that stays in sight while it is out of view."""
        if len(self.turns) < 2:
            return ""
        arrow = "↑" if self.newest_first else "↓"
        return (
            f'<a class="to-newest" href="#t{self.newest}" title="Go to the newest turn (G)">'
            f"Newest turn, {self.newest} {arrow}<kbd>G</kbd></a>"
        )

    def spans(self) -> list[tuple[int, int, bool]]:
        """A long session's chapters as (start, end, open), in the order they are read:
        a few turns open at the end it is read from, the rest folded in tens away from it."""
        total = len(self.turns)
        if not self.newest_first:
            rest = range(OPEN_HEAD, total, CHAPTER)
            return [(0, OPEN_HEAD, True)] + [(s, min(s + CHAPTER, total), False) for s in rest]
        head = total - OPEN_HEAD
        rest = range(head, 0, -CHAPTER)
        return [(head, total, True)] + [(max(0, e - CHAPTER), e, False) for e in rest]

    def chapters(self) -> str:
        """A long session with only its first few turns open (or its newest): the rest
        folds into chapters of ten, each a line that says when it happened, what it changed
        and what it became. Everything is on the page, so links to a turn, find in page
        and search marks still reach it. The bar of controls sits on its own line above."""
        rendered = [TurnView(self, turn).to_html() for turn in self.turns]
        if len(rendered) <= LONG_SESSION:
            return self.turn_bar() + "".join(self.in_order(rendered))
        return self.turn_bar() + "".join(
            f'<details class="chapter" id="turns-{start + 1}"{" open" if opened else ""}>'
            f"<summary>{self.chapter_line(start + 1, end)}</summary>"
            f"{''.join(self.in_order(rendered[start:end]))}</details>"
            for start, end, opened in self.spans()
        )

    def chapter_line(self, first: int, last: int) -> str:
        turns = self.turns[first - 1 : last]
        starts = [at for turn in turns if (at := moment(turn.started_at))]
        bits = [_moments(starts[0], starts[-1])] if starts else []
        if changed := len({path for turn in turns for path in turn.changed_files}):
            bits.append(f"{plural(changed, 'file')} changed")
        if items := len({i.id for n in range(first, last + 1) for i in self.learned.get(n, [])}):
            bits.append(f"{items} became knowledge")
        label = f"Turns {first}–{last}" if last > first else f"Turn {first}"
        return (
            f'<span class="chapter-name">{label}</span><span class="chapter-meta">{" · ".join(bits)}</span>'
            '<span class="chapter-toggle" aria-hidden="true"></span>'
        )

    def index(self) -> str:
        """Turns, files, tasks and subagents beside the reading: as tabs with the page
        script, so a long list of turns never hides the files below it; one after the
        other without it."""
        parts = (part.to_html() for part in IndexPart.all_of(self))
        return f'<aside class="index" aria-label="Index">{INDEX_TOOLS}{"".join(parts)}</aside>'


def _moments(first: datetime, last: datetime) -> str:
    """When a run of turns started, from the first to the last, in local time."""
    a, b = first.astimezone(), last.astimezone()
    if a == b:
        return f"{a:%d %b %H:%M}"
    return f"{a:%d %b %H:%M} – " + (f"{b:%H:%M}" if a.date() == b.date() else f"{b:%d %b %H:%M}")


@dataclass(frozen=True)
class Figure:
    """One figure at a glance: what it is, the number, two lines that say it in words, and
    where it is taken apart. `raw` lines are HTML already."""

    link: str
    label: str
    figure: str
    first: str
    second: str
    tip: str
    raw: bool = False

    def to_html(self) -> str:
        first = self.first if self.raw else escape(self.first)
        return (
            f'<a class="g" href="{escape(self.link)}" title="{escape(self.tip)}">'
            f'<span class="g-label">{escape(self.label)}</span><span class="g-num">{escape(self.figure)}</span>'
            f'<span class="g-sub">{first}</span><span class="g-sub">{escape(self.second)}</span></a>'
        )


@dataclass(frozen=True)
class Glance:
    """The figures above a session, in the order they are read."""

    page: SessionPage

    def figures(self) -> Iterator[Figure]:
        found = (
            self.work_time(),
            self.asks(),
            self.tasks(),
            self.agents(),
            self.files(),
            self.checks(),
            self.knowledge(),
            self.tokens(),
        )
        return (figure for figure in found if figure)

    def work_time(self) -> Figure | None:
        line = self.page.line
        if not line or line.active_seconds <= 0:
            return None
        you, active = line.seconds_in("you"), line.active_seconds
        wall = self.page.session.wall_seconds
        over = f"over {duration(wall)}" if wall > active + 60 else "without a break"
        return Figure(
            "#timeline",
            "Work time",
            duration(active),
            f"you {unbroken(duration(you))}, assistant {unbroken(duration(active - you))}",
            over,
            "Time someone was working, you reading and writing or the assistant at work; "
            "the gaps when nobody was are left out",
        )

    def asks(self) -> Figure:
        session = self.page.session
        return Figure(
            "#index-turns",
            "Asks",
            str(len(session.asks)),
            plural(session.tool_calls, "tool call"),
            "listed in the index",
            "What you asked; each starts a turn",
        )

    def tasks(self) -> Figure | None:
        if not (tasks := self.page.tasks):
            return None
        unfinished = tasks.unfinished
        return Figure(
            "#index-tasks",
            "Tasks",
            f"{tasks.done}/{len(tasks)}",
            "done",
            f"{unfinished} left open" if unfinished else "none left open",
            "The checklist the assistant kept while it worked, where each task ended",
        )

    def agents(self) -> Figure | None:
        if not (runs := self.page.session.agents):
            return None
        calls = sum(r.tool_uses or sum(1 for e in r.steps if e.tool) for r in runs)
        failed = sum(1 for r in runs if r.failed)
        return Figure(
            "#index-agents",
            "Subagents",
            str(len(runs)),
            f"{plural(calls, 'tool call')} between them",
            f"{failed} failed" if failed else "open one for its run",
            "Helpers the assistant sent off to work on their own; open one to see its run",
        )

    def files(self) -> Figure | None:
        page = self.page
        if not (edited := page.edited):
            return None
        added, removed = Change.totals(Change.all_in(page.session))
        folders = len({page.relative(path).rpartition("/")[0] for path in edited})
        return Figure(
            "#index-files",
            "Files changed",
            str(len(edited)),
            f'<span class="plus">+{added:,}</span> <span class="minus">−{removed:,}</span> lines',
            f"in {plural(folders, 'folder')}",
            "Files the assistant changed; open one in the index to see its changes, stacked by turn",
            raw=True,
        )

    def checks(self) -> Figure | None:
        line = self.page.line
        if not line or not line.checks:
            return None
        failed = line.failed_checks
        return Figure(
            "#timeline",
            "Checks",
            str(line.checks),
            f'<span class="err">{failed} failed</span>' if failed else "none failed",
            f"{plural(line.cycles, 'round')} of edit, then pass",
            "Tests, linters and type checks the assistant ran. A round is a change followed "
            "by a check that passed: how often the work was proven",
            raw=True,
        )

    def knowledge(self) -> Figure:
        tip = "Preferences and facts drawn from your words in this session"
        items = {i.id: i for found in self.page.learned.values() for i in found}
        if not items:
            pick = href("/knowledge/pick", s=self.page.session.id)
            return Figure(
                pick,
                "Knowledge",
                "—",
                "nothing extracted yet",
                "extract preferences and facts",
                tip,
            )
        waiting = sum(1 for i in items.values() if i.status == "candidate")
        return Figure(
            href("/knowledge", view="" if waiting else "accepted"),
            "Knowledge",
            str(len(items)),
            f"{waiting} to review" if waiting else "all accepted",
            "bulbs mark their turns",
            tip,
        )

    def tokens(self) -> Figure | None:
        line = self.page.line
        if not line or not (tokens := line.tokens_in()).total:
            return None
        return Figure(
            "#timeline",
            "Tokens",
            count(tokens.total),
            f"{count(tokens.output)} written",
            f"{count(tokens.cache_read)} from cache",
            "What the model calls in this session consumed",
        )


@dataclass(frozen=True)
class IndexPart:
    """One list in the index beside the turns, a tab when the page script runs."""

    key: str
    tab: str
    count: int
    heading: str  # HTML
    body: str  # HTML

    @classmethod
    def all_of(cls, page: SessionPage) -> list["IndexPart"]:
        found = (cls.turns(page), cls.files(page), cls.tasks(page), cls.agents(page))
        return [part for part in found if part]

    @classmethod
    def turns(cls, page: SessionPage) -> "IndexPart":
        def bulb(n: int) -> str:
            if not (items := len(page.learned.get(n, []))):
                return ""
            return f'<span class="kn-mark" title="{items} became knowledge">{icon("bulb")}</span>'

        rows = [
            f'<li data-filter="{escape(turn.label.lower()[:300])}">{page.view.turn_meters.get(turn.number, "")}'
            f'<a href="#t{turn.number}" title="{escape(clip(turn.label, 300))}">{bulb(turn.number)}{escape(clip(turn.label, 120))}</a></li>'
            for turn in page.turns
        ]
        n = len(page.turns)
        heading = f'Turns <span class="n">{n}</span> <kbd>j</kbd><kbd>k</kbd>'
        reversed_ = " reversed" if page.newest_first else ""  # numbered n down to 1
        body = f'<ol class="turn-list"{reversed_}>{"".join(page.in_order(rows))}</ol>'
        return cls("turns", "Turns", n, heading, body)

    @classmethod
    def files(cls, page: SessionPage) -> "IndexPart | None":
        if not (n := len(page.edited)):
            return None
        heading = f'Files edited <span class="n">{n}</span>'
        return cls("files", "Files", n, heading, FileTree.of(page).to_html())

    @classmethod
    def tasks(cls, page: SessionPage) -> "IndexPart | None":
        if not (tasks := page.tasks):
            return None
        rows = "".join(task_row(task, page.live) for task in tasks)
        heading = f'Tasks <span class="n">{tasks.done}/{len(tasks)}</span>'
        body = f'\n  {TASK_KEY}\n  <ol class="task-list">{rows}</ol>'
        return cls("tasks", "Tasks", len(tasks), heading, body)

    @classmethod
    def agents(cls, page: SessionPage) -> "IndexPart | None":
        session = page.session
        if not (n := len(session.agents)):
            return None
        spawned = session.spawned_in()
        rows = "".join(
            RunView(session, run, page.at).index_row(spawned.get(run.id)) for run in session.agents
        )
        heading = f'Subagents <span class="n">{n}</span>'
        return cls("agents", "Agents", n, heading, f'<ul class="agent-list">{rows}</ul>')

    def to_html(self) -> str:
        return f"""<section class="index-part" id="index-{self.key}" data-tab="{self.tab}" data-count="{self.count}">
  <h2 class="label">{self.heading}</h2>{self.body}</section>"""


@dataclass(frozen=True)
class TurnView:
    """One turn as it reads: its number and margin line, the ask, the knowledge it became,
    the folded work, the helpers it sent off, the answer, and what happened besides."""

    page: SessionPage
    turn: Turn

    @property
    def project(self) -> Path:
        return self.page.session.project

    def to_html(self) -> str:
        turn, session = self.turn, self.page.session
        n = turn.number
        ask = ask_html(turn.ask) if turn.ask else ""
        at = self.page.at
        agents = "".join(RunView(session, run, at).card() for run in session.agents_in(turn))
        events = "".join(event_html(e) for e in turn.events)
        return (
            f'<section class="turn" id="t{n}"><a class="num" href="#t{n}" aria-label="Turn {n}">{n}</a>'
            f"{self.meta()}{ask}{self.learned()}{self.work()}{agents}{self.answer()}{events}</section>"
        )

    def meta(self) -> str:
        """When the turn started, how long the assistant worked, what it changed, and the
        tasks it moved."""
        turn, page = self.turn, self.page
        bits = []
        if at := moment(start := turn.started_at):
            bits.append(f'<time datetime="{escape(start or "")}">{at.astimezone():%H:%M}</time>')
        if (seconds := page.view.turn_seconds.get(turn.number)) and seconds >= 1:
            bits.append(f"<span>{duration(seconds)} of work</span>")
        if turn.changed_files:
            bits.append(self.changed())
        if chips := task_chips(page.tasks.moved_in(turn.number)):
            bits.append(chips)
        # A div, not a p: a <details> inside a <p> makes the parser close the p before it.
        return f'<div class="turn-meta">{"".join(bits)}</div>' if bits else ""

    def changed(self) -> str:
        session, n = self.page.session, self.turn.number
        links = [
            f'<a class="file" href="{escape(file_href(f, session, n))}" data-panel title="{escape(f)}: this turn\'s changes, in its stack">{escape(Path(f).name)}</a>'
            for f in self.turn.changed_files
        ]
        names = "".join(links[:MAX_META_FILES])
        if rest := links[MAX_META_FILES:]:
            # Spaces between the names: once opened they flow as text and must wrap.
            names += f'<details class="more-files"><summary>+{len(rest)} more</summary>{" ".join(rest)}</details>'
        return f'<div class="changed">{icon("file")}{names}</div>'

    def learned(self) -> str:
        """The knowledge this turn became, right under your words: what kind, whether it
        still waits for your review, and the statement in reading type."""
        if not (items := self.page.learned.get(self.turn.number, [])):
            return ""
        rows = "".join(_knowledge_note(item) for item in items)
        heading = "Became knowledge" + (f" · {len(items)}" if len(items) > 1 else "")
        return (
            f'<aside class="learned" aria-label="Knowledge from this turn">'
            f'<p class="learned-head">{icon("bulb")}{heading}</p><ul>{rows}</ul></aside>'
        )

    def work(self) -> str:
        """Every step but the answer, folded under a line that counts them by tool."""
        turn = self.turn
        if not (work := turn.work):
            return ""
        tools = " · ".join(f"{name} {n}" for name, n in turn.tool_counts.items())
        errors = sum(1 for step in work if step.failed)
        failed = f' <span class="err">· {errors} failed</span>' if errors else ""
        label = f"<b>{len(work)} steps</b>" + (f" — {escape(tools)}" if tools else "")
        steps = "".join(step_html(step, self.project) for step in work)
        return f'<details class="work"><summary>{label}{failed}</summary><ol class="steps">{steps}</ol></details>'

    def answer(self) -> str:
        if not (answer := self.turn.answer):
            return ""
        text = render_markdown(answer.text, self.project)
        return f'<div class="answer">{source(answer)}<div class="md">{text}</div></div>'


def _knowledge_note(item: Item) -> str:
    accepted = item.status == "accepted"
    where = "everywhere" if item.scope == GLOBAL else f"in {scope_name(item.scope)}"
    return f'''<li class="kn-note {"accepted" if accepted else "to-review"}">
  <p class="kn-tags"><span class="kind">{escape(item.kind)}</span><span>{escape(item.category)}</span><span>{escape(where)}</span>
    <a class="state" href="{escape(knowledge_href(item))}">{"Accepted" if accepted else "Review"}</a></p>
  <p class="kn-statement">{escape(item.statement)}</p></li>'''


@dataclass
class Folder:
    """A folder of edited files: the folders in it, and the files right in it."""

    folders: dict[str, "Folder"] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)  # absolute paths

    def __len__(self) -> int:
        return len(self.files) + sum(len(f) for f in self.folders.values())

    def add(self, path: str, shown: str) -> None:
        """File `path` under its folders as `shown` names them."""
        node = self
        for name in shown.strip("/").split("/")[:-1]:
            node = node.folders.setdefault(name, Folder())
        node.files.append(path)

    def subfolders(self) -> Iterator[tuple[str, "Folder"]]:
        """By name; a chain of single folders comes as one (`src/matters`)."""
        for name, sub in sorted(self.folders.items(), key=lambda kv: kv[0].lower()):
            while len(sub.folders) == 1 and not sub.files:
                ((child, sub),) = sub.folders.items()
                name = f"{name}/{child}"
            yield name, sub


@dataclass(frozen=True)
class FileTree:
    """Edited files as the tree they live in: folders that fold, with how many files each
    holds, files outside the project in a folded branch of their own."""

    page: SessionPage
    inside: Folder
    outside: Folder

    @classmethod
    def of(cls, page: SessionPage) -> "FileTree":
        inside, outside, home = Folder(), Folder(), str(Path.home())
        for path in page.edited:
            relative = page.relative(path)
            if not relative.startswith("/"):
                inside.add(path, relative)
            elif relative.startswith(f"{home}/"):
                outside.add(path, "~" + relative[len(home) :])
            else:
                outside.add(path, relative)
        return cls(page, inside, outside)

    def to_html(self) -> str:
        rows = self.rows(self.inside)
        if self.outside:
            outside = '<span class="outside">outside the project</span>'
            rows += self.folder_row(outside, self.outside, opened=False)
        return f'<ul class="files tree">{rows}</ul>'

    def rows(self, folder: Folder) -> str:
        folders = (self.folder_row(breakable(name), sub) for name, sub in folder.subfolders())
        files = (self.file_row(p) for p in sorted(folder.files, key=lambda p: Path(p).name.lower()))
        return "".join(folders) + "".join(files)

    def folder_row(self, name: str, folder: Folder, opened: bool = True) -> str:
        n = len(folder)
        return (
            f'<li class="folder"><details{" open" if opened else ""}><summary>'
            f'<span class="folder-name">{name}</span><span class="count" title="{n} edited">{n}</span></summary>'
            f"<ul>{self.rows(folder)}</ul></details></li>"
        )

    def file_row(self, path: str) -> str:
        session, turns = self.page.session, self.page.edited[path]
        stack = escape(file_href(path, session))
        refs = "".join(f"<a href=#t{n}>{n}</a>" for n in turns[:MAX_REFS])
        if (more := len(turns) - MAX_REFS) > 0:
            refs += f'<a class="more-refs" href="{stack}" data-panel title="{more} more: see the stack">+{more}</a>'
        return (
            f'<li data-filter="{escape(self.page.relative(path).lower())}"><a class="file" href="{stack}" data-panel title="{escape(path)}: its changes, stacked">'
            f"<code>{escape(Path(path).name)}</code></a>"
            f'<span class="turn-refs">{refs}</span></li>'
        )
