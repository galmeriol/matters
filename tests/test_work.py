"""Tasks and subagents: read from the journal, and given places of their own on the page."""

import re
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from matters.session import Entry, Session, SourceRef, ToolCall
from matters.sources.claude_code import ClaudeCode
from matters.sources.claude_tags import notifications
from matters.tasks import ACTIVE, Task, TaskList
from matters.timeline import Timeline
from matters.web import frame
from matters.web.agent_page import agent_panel
from matters.web.app import Viewer
from matters.web.frame import rail
from matters.web.library import Library
from matters.web.session_page import session_page
from matters.web.text import ago, milliseconds, model_name, short_date, short_duration
from matters.web.tool_views import ToolView
from matters.web.work_views import task_row
from tests.fakes import FIXTURES

ROOT = FIXTURES / "claude-agents"


@pytest.fixture
def session() -> Session:
    (found,) = ClaudeCode(root=ROOT).sessions()
    return found


@pytest.fixture
def viewer() -> Viewer:
    return Viewer([ClaudeCode(root=ROOT)])


def page(viewer: Viewer, path: str, query: str = "") -> str:
    response = viewer.route(path, query)
    assert response.status == "200 OK", response.status
    return response.body


def text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_a_background_subagent_is_read_with_its_transcript_and_its_notice(session: Session) -> None:
    run = session.agent("a1b2c3")
    assert run is not None
    assert (run.call_id, run.kind, run.description) == (
        "tu4",
        "Explore",
        "Count files in directory",
    )
    assert run.background and run.status == "completed" and run.finished
    assert run.report.startswith("There are 2 files")
    assert (run.duration_ms, run.tokens, run.tool_uses) == (2721, 18657, 1)
    assert run.model == "claude-haiku-5-5"
    assert [e.tool.name for e in run.steps if e.tool] == ["Glob"]


def test_a_subagent_run_in_the_foreground_gets_its_figures_from_the_call_result(
    session: Session,
) -> None:
    run = session.agent_for("tu6")
    assert run is not None and run.id == "d4e5f6"
    assert not run.background and run.finished
    assert (run.duration_ms, run.tokens, run.tool_uses) == (6400, 9120, 2)
    assert run.report == "It covers installing and running the tool."
    assert [e.tool.name for e in run.steps if e.tool] == ["Read", "Grep"]


def test_subagent_records_never_leak_into_the_session(session: Session) -> None:
    tools = [e.tool.name for e in session.entries if e.tool]
    assert "Glob" not in tools and "Grep" not in tools
    assert len(session.turns) == 2


def test_a_notification_is_read_as_its_fields() -> None:
    (notice,) = notifications(
        "<task-notification><task-id>x1</task-id><status>completed</status>"
        "<result>ok</result><usage><subagent_tokens>12</subagent_tokens>"
        "<duration_ms>34</duration_ms></usage></task-notification>"
    )
    assert notice["task-id"] == "x1" and notice["status"] == "completed"
    assert notice["subagent_tokens"] == "12" and notice["duration_ms"] == "34"


def test_the_task_list_is_replayed_from_the_calls_that_kept_it(session: Session) -> None:
    tasks = list(TaskList.from_session(session))
    assert [(t.id, t.subject, t.status) for t in tasks] == [
        ("1", "Count the files", "completed"),
        ("2", "Fix the typo in the README", "pending"),
    ]
    assert tasks[0].moves == [(1, "pending"), (1, "in_progress"), (1, "completed")]


def call(name: str, given: dict[str, Any], result: str = "", error: bool = False) -> Entry:
    return Entry("tool", "", SourceRef(Path("x"), 1), tool=ToolCall(name, given, result, error))


def one_turn(*steps: Entry) -> Session:
    ask = Entry("ask", "go", SourceRef(Path("x"), 1))
    return Session("s", "claude", Path("/p"), (ask, *steps))


def test_todo_write_rewrites_the_list_and_a_dropped_todo_is_gone() -> None:
    first = {
        "todos": [{"content": "a", "status": "pending"}, {"content": "b", "status": "pending"}]
    }
    second = {"todos": [{"content": "a", "status": "completed"}]}
    tasks = list(
        TaskList.from_session(one_turn(call("TodoWrite", first), call("TodoWrite", second)))
    )
    assert [(t.subject, t.status) for t in tasks] == [("a", "completed")]


def test_failed_task_calls_change_nothing() -> None:
    made = call("TaskCreate", {"subject": "x"}, "Task #1 created successfully: x")
    broken = call("TaskUpdate", {"taskId": "1", "status": "completed"}, "no", error=True)
    (task,) = list(TaskList.from_session(one_turn(made, broken)))
    assert task.status == "pending" and task.id == "1"


def test_the_header_counts_tasks_and_subagents(viewer: Viewer) -> None:
    html = page(viewer, "/s/s4")
    glance = text(
        html[html.index('class="glance"') : html.index("</nav>", html.index('class="glance"'))]
    )
    assert "Tasks 1/2 done 1 left open" in glance
    assert "Subagents 2" in glance
    assert 'href="#index-tasks"' in html and 'href="#index-agents"' in html
    assert "1 task never marked done" in text(html)


def test_a_turn_shows_its_subagent_as_a_card_with_the_way_into_the_run(viewer: Viewer) -> None:
    html = page(viewer, "/s/s4")
    first = html[html.index('id="t1"') : html.index('id="t2"')]
    card = first[first.index('class="agent-run') :]
    card = card[: card.index("</aside>")]
    assert "Explore" in card and "Count files in directory" in card
    assert "done" in card and "Haiku 5.5" in card and "19k tokens" in card
    assert "There are 2 files" in card  # a short report is shown on the card
    assert 'href="/s/s4/agents/a1b2c3" data-panel' in card
    assert card.index("agent-run") > 0 and first.index("agent-run") > first.index(
        'details class="work"'
    )


def test_a_turn_names_the_tasks_it_moved(viewer: Viewer) -> None:
    html = page(viewer, "/s/s4")
    meta = html[html.index('id="t1"') :]
    meta = meta[
        meta.index('class="turn-meta"') : meta.index(
            "</div></div>", meta.index('class="turn-meta"')
        )
    ]
    assert 'class="task-chip completed" href="#task-1"' in meta
    assert 'class="task-chip pending" href="#task-2"' in meta


def test_the_index_lists_tasks_and_subagents(viewer: Viewer) -> None:
    html = page(viewer, "/s/s4")
    tasks = html[
        html.index('id="index-tasks"') : html.index("</section>", html.index('id="index-tasks"'))
    ]
    assert 'id="task-1" class="task completed"' in tasks and "Fix the typo in the README" in tasks
    agents = html[html.index('id="index-agents"') :]
    assert agents.count('class="agent"') == 2
    assert '<a href="#t2">2</a>' in agents  # the turn that started the second one


def test_a_run_opens_as_a_page_and_in_the_drawer(viewer: Viewer) -> None:
    html = page(viewer, "/s/s4/agents/d4e5f6")
    words = text(html)
    assert "What it was asked" in words and "What it did" in words and "What it reported" in words
    assert "It covers installing and running the tool." in words
    assert words.count("It covers installing") == 1  # its closing words only as the report
    assert ">Read<" in html and ">Grep<" in html
    assert 'href="/s/s4#t2"' in html
    panel = page(viewer, "/s/s4/agents/d4e5f6", "panel=1")
    assert panel.startswith('<div class="panel-head">') and 'class="rail"' not in panel


def test_an_unknown_run_is_404(viewer: Viewer) -> None:
    assert viewer.route("/s/s4/agents/nope", "").status == "404 Not Found"
    assert viewer.route("/s/nope/agents/a1b2c3", "").status == "404 Not Found"


def test_task_and_agent_calls_read_as_words_in_the_steps() -> None:
    def summary(name: str, given: dict[str, Any]) -> str:
        return ToolView.for_(ToolCall(name, given, ""), Path("/p")).summary()

    assert summary("TaskCreate", {"subject": "Ship it"}) == "Added: Ship it"
    assert summary("TaskUpdate", {"taskId": "3", "status": "in_progress"}) == "#3 → in progress"
    todos = {
        "todos": [
            {"content": "a", "status": "completed"},
            {"content": "b", "status": "in_progress", "activeForm": "Doing b"},
        ]
    }
    assert summary("TodoWrite", todos) == "1/2 done · now: Doing b"
    assert summary("Agent", {"subagent_type": "Explore", "description": "Look"}) == "Explore: Look"


def test_model_names_and_run_times_read_plainly() -> None:
    assert model_name("claude-haiku-5-5") == "Haiku 5.5"
    assert model_name("claude-sonnet-4-5-20250929") == "Sonnet 4.5"
    assert model_name("gpt-x") == "gpt-x"
    assert milliseconds(2721) == "2.7 s" and milliseconds(64_000) == "64 s"
    assert milliseconds(600_000) == "10 min"


def at_work(session: Session) -> tuple[Session, datetime]:
    """The session with its second subagent still at work (no result yet), and a moment
    half a minute after its last step."""
    run = session.agent("d4e5f6")
    assert run is not None
    working = replace(run, status="", report="")
    agents = tuple(working if a.id == run.id else a for a in session.agents)
    live = replace(session, agents=agents)
    assert live.last_activity is not None
    return live, live.last_activity + timedelta(seconds=30)


def test_a_session_is_live_while_its_journals_are_still_being_written(session: Session) -> None:
    live, at = at_work(session)
    assert live.is_live(at) and [r.id for r in live.running_agents(at)] == ["d4e5f6"]
    later = at + timedelta(minutes=10)
    assert not live.is_live(later) and not live.running_agents(later)
    finished = session.agent("a1b2c3")
    assert finished is not None and not finished.is_running(at)  # it has its result


def test_a_session_still_being_written_says_so_and_offers_a_refresh(session: Session) -> None:
    live, at = at_work(session)
    html = session_page(Library([live]), live, at=at)
    words = text(html)
    assert "Running Still being written · last activity 30 s ago · 1 subagent at work" in words
    bar = html[html.index('<div class="turn-bar">') :]  # above the turns, where they will show
    assert bar.startswith('<div class="turn-bar"><a class="refresh" href="/s/s4" data-refresh')
    assert 'class="refresh"' not in html[: html.index('<div class="turn-bar">')]
    assert "never marked done" not in words  # it has not ended yet
    card = html[html.index('id="t2"') :]
    assert '<aside class="agent-run running"' in card and ">running</span>" in card
    agents = html[html.index('id="index-agents"') :]
    assert '<li class="running"' in agents


def test_a_run_still_at_work_says_so_in_the_drawer(session: Session) -> None:
    live, at = at_work(session)
    run = live.agent("d4e5f6")
    assert run is not None
    panel = agent_panel(Library([live]), live, run, at)
    assert '<span class="agent-state running">running</span>' in panel
    assert "Last step" in text(panel) and "Still at work" in text(panel)
    assert 'href="/s/s4/agents/d4e5f6" data-refresh' in panel


def test_a_run_that_went_quiet_without_a_result_reads_as_stopped(session: Session) -> None:
    live, at = at_work(session)
    run = live.agent("d4e5f6")
    assert run is not None
    panel = agent_panel(Library([live]), live, run, at + timedelta(minutes=10))
    assert "stopped without a result" in panel and "data-refresh" not in panel
    assert "its journal went quiet before it finished" in text(panel)


def test_an_old_session_is_a_record_not_running(viewer: Viewer) -> None:
    html = page(viewer, "/s/s4")
    main = html[html.index("<main") : html.index("</main>")]
    assert "Still being written" not in main and 'class="pulse"' not in html


def test_the_task_in_progress_pulses_only_while_the_session_is_live() -> None:
    task = Task("3", "Write the tests", status=ACTIVE)
    assert 'class="task in_progress live"' in task_row(task, live=True)
    assert 'class="task in_progress"' in task_row(task, live=False)
    assert 'class="task pending"' in task_row(Task("4", "Later"), live=True)


def test_the_rail_marks_a_session_still_being_written(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, at = at_work(session)
    monkeypatch.setattr(frame, "now", lambda: at)
    html = rail(Library([live]), "/")
    assert 'class="pulse" title="Still being written"' in html
    monkeypatch.setattr(frame, "now", lambda: at + timedelta(hours=1))
    assert 'class="pulse"' not in rail(Library([live]), "/")


def test_how_long_ago_reads_plainly() -> None:
    assert [ago(s) for s in (3, 42.7, 125, 3 * 3600 + 300)] == [
        "just now",
        "42 s ago",
        "2 min ago",
        "3 h 5 min ago",
    ]


def test_a_chart_gives_times_briefly() -> None:
    assert [short_duration(s) for s in (8, 1080, 2 * 3600 + 27 * 60, 3600 + 5 * 60)] == [
        "8s",
        "18m",
        "2h 27m",
        "1h 05m",
    ]


def test_the_rail_reads_like_a_book_s_contents(session: Session) -> None:
    html = rail(Library([session]), "/", current=session)
    work = short_duration(Timeline.of(session).active_seconds)
    assert (
        f'<span class="leader" aria-hidden="true"></span><span class="figure">{work}</span>' in html
    )
    assert 'class="current" aria-current="page"' in html
    # with neither a title nor an ask there is nothing to call it by
    quiet = replace(session, title=None, entries=tuple(e for e in session.entries if not e.is_ask))
    assert '<span class="title">untitled</span>' in rail(Library([quiet]), "/")
    # the one you are reading opens into a card: its day and asks, and when work happened
    card = html[html.index('class="current"') :]
    assert f'<span class="date">{short_date(session.started_at)} · {len(session.asks)} ask' in card
    assert '<span class="strip" aria-hidden="true"><i' in card
    assert '<span class="strip"' not in rail(Library([session]), "/")
    assert f'<span class="title">{quiet.id}' not in rail(Library([quiet]), "/")
