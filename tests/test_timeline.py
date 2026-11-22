"""How a session's time was spent: classification, the clock, debug periods, cycles."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from matters.session import Entry, Session, SourceRef, ToolCall
from matters.timeline import STEP_CAP, YOU_CAP, Timeline, classify

REF = SourceRef(Path("x.jsonl"), 1)


START = datetime(2026, 11, 17, 10, tzinfo=UTC)


def at(seconds: int) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def ask(t: int, text: str = "do it") -> Entry:
    return Entry("ask", text, REF, at=at(t))


def say(t: int, text: str = "ok") -> Entry:
    return Entry("text", text, REF, at=at(t))


def bash(t: int, command: str, done: int, *, failed: bool = False) -> Entry:
    call = ToolCall("Bash", {"command": command}, "", failed, at(done))
    return Entry("tool", "", REF, call, at=at(t))


def tool(t: int, name: str, done: int) -> Entry:
    return Entry("tool", "", REF, ToolCall(name, {}, "", False, at(done)), at=at(t))


def session(*entries: Entry) -> Session:
    return Session("x", "claude-code", Path("/tmp/x"), entries)


@pytest.mark.parametrize(
    ("command", "activity"),
    [
        ("uv run pytest -q 2>&1 | tail -3", "verify"),
        ("make check", "verify"),
        ("npm run lint", "verify"),
        ("curl -s http://127.0.0.1:8765/map | grep x", "verify"),
        ("cargo test", "verify"),
        ("cat src/app.py && grep -n foo src", "explore"),
        ("ls -la > /dev/null 2>&1", "explore"),
        ("sed -n 1,40p file.py", "explore"),
        ("sed -i '' 's/a/b/' file.py", "build"),
        ("mkdir -p src/pkg", "build"),
        ("uv add httpx", "build"),
        ("python3 - <<'EOF'\nPath('a').write_text('x')\nEOF", "build"),
        ("echo hi > notes.txt", "build"),
        ("uv run matters serve --no-open", "run"),
        ("git commit -m wip", "run"),
    ],
)
def test_shell_commands_are_classified_by_what_they_do(command: str, activity: str) -> None:
    assert classify(bash(0, command, 1)) == activity


def test_tools_are_classified_by_name() -> None:
    assert classify(tool(0, "Read", 1)) == "explore"
    assert classify(tool(0, "Edit", 1)) == "build"
    assert classify(tool(0, "WebSearch", 1)) == "explore"
    assert classify(tool(0, "TodoWrite", 1)) == "discuss"
    assert classify(ask(0)) == "you"
    assert classify(say(0)) == "discuss"


def test_each_step_owns_the_time_since_the_last_event_plus_its_run_time() -> None:
    line = Timeline.of(
        session(
            ask(0),
            say(10, "I'll edit it"),  # 10 s writing, leads to an edit: build
            tool(15, "Edit", 16),  # 5 s composing + 1 s running
            bash(20, "pytest", 50),  # 4 s + 30 s
            say(60, "Done."),  # the last word in the turn: discuss
            ask(180, "thanks"),  # you: 2 min reading and writing
        )
    )
    assert [(s.activity, s.seconds) for s in line.steps] == [
        ("you", 0),
        ("build", 10),
        ("build", 6),
        ("verify", 34),
        ("discuss", 10),
        ("you", 120),
    ]
    assert line.active_seconds == 180
    assert line.turn_spans == {1: (0, 60)}


def test_work_after_a_failed_check_is_debugging_until_one_passes() -> None:
    line = Timeline.of(
        session(
            ask(0),
            tool(5, "Edit", 6),
            bash(10, "pytest", 20, failed=True),
            tool(30, "Read", 31),
            tool(40, "Edit", 41),
            bash(50, "pytest", 60),
            tool(70, "Edit", 71),
        )
    )
    assert [s.activity for s in line.steps] == [
        "you", "build", "verify", "debug", "debug", "verify", "build",
    ]  # fmt: skip
    assert (line.checks, line.failed_checks) == (2, 1)
    assert line.cycles == 1  # build -> fail -> debug -> pass


def test_long_gaps_count_as_away_not_as_work() -> None:
    back = 5 + YOU_CAP + 3600
    line = Timeline.of(session(ask(0), say(5), ask(back), tool(7200, "Read", 7200 + STEP_CAP + 60)))
    you = [s.seconds for s in line.steps if s.activity == "you"]
    assert you == [0, YOU_CAP]
    assert line.away_seconds == pytest.approx(3600 + (7200 - back - STEP_CAP) + 60)
    assert line.steps[-1].seconds == 2 * STEP_CAP  # composing and running, each capped


def test_merged_segments_keep_the_turn_they_start_in() -> None:
    line = Timeline.of(
        session(ask(0), tool(5, "Edit", 6), tool(8, "Write", 9), ask(20), tool(25, "Read", 26))
    )
    assert [(s.activity, s.turn, s.steps) for s in line.segments] == [
        ("build", 1, 2), ("you", 2, 1), ("explore", 2, 1),
    ]  # fmt: skip


def test_sessions_without_timestamps_have_no_time() -> None:
    line = Timeline.of(session(Entry("ask", "hi", REF), Entry("text", "hello", REF)))
    assert line.active_seconds == 0 and line.segments == ()


def test_tokens_add_up_per_activity_and_per_turn() -> None:
    from matters.session import Tokens

    edit_call = ToolCall("Edit", {}, "", False, at(6))
    test_call = ToolCall("Bash", {"command": "pytest"}, "", False, at(20))
    edit = Entry("tool", "", REF, edit_call, at=at(5), tokens=Tokens(1, 100, 0, 1000))
    test = Entry("tool", "", REF, test_call, at=at(10), tokens=Tokens(1, 50, 10, 2000))
    line = Timeline.of(session(ask(0), edit, test, ask(30), say(35)))
    assert line.tokens_in("build").output == 100
    assert line.tokens_in("verify").cache_read == 2000
    assert line.tokens_in().total == 1101 + 2061
    assert line.turn_tokens[1].output == 150 and line.turn_tokens[2].total == 0


def test_weight_favours_output_over_cached_reads() -> None:
    from matters.session import Tokens

    assert Tokens(output=1000).weight > Tokens(cache_read=10_000).weight


@pytest.mark.parametrize(
    ("weight", "expected"),
    [(0, "none"), (40, "low"), (100, "medium"), (199, "medium"), (200, "high")],
)
def test_levels_are_relative_to_the_session_average(weight: float, expected: str) -> None:
    from matters.web.timeline_view import level

    assert level(weight, 100) == expected
