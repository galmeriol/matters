"""How a session ended, and what a project's brief says about it."""

from pathlib import Path

from matters.brief import Brief, Loose
from matters.session import Entry, Session, SourceRef, ToolCall

REF = SourceRef(Path("x.jsonl"), 1)


def session(*entries: Entry, sid: str = "s") -> Session:
    return Session(sid, "claude-code", Path("/p"), entries, started_at="2026-11-01T10:00:00Z")


def ask(text: str) -> Entry:
    return Entry("ask", text, REF)


def say(text: str) -> Entry:
    return Entry("text", text, REF)


def run(command: str, failed: bool = False) -> Entry:
    return Entry("tool", "", REF, ToolCall("Bash", {"command": command}, "out", failed))


def test_a_finished_session_has_no_loose_end() -> None:
    assert Loose.of(session(ask("fix it"), run("pytest"), say("Fixed; tests pass."))) is None


def test_a_closing_question_is_left_open() -> None:
    found = Loose.of(session(ask("add a cache"), say("Done.\n\n**Should I also cache misses?**")))
    assert found is not None and found.ending == "question"
    assert found.text == "Should I also cache misses?"


def test_a_check_still_failing_at_the_end_is_left_open() -> None:
    found = Loose.of(session(ask("fix"), run("uv run pytest -q", failed=True), say("Still red.")))
    assert found is not None and found.ending == "failing" and "pytest" in found.text
    green = session(ask("fix"), run("pytest", failed=True), run("pytest"), say("Green."))
    assert Loose.of(green) is None


def test_an_ask_without_an_answer_and_an_interruption_are_left_open() -> None:
    silent = Loose.of(session(ask("first"), say("ok"), ask("and then?")))
    assert silent is not None and silent.ending == "unanswered" and silent.turn == 2
    stopped = session(ask("go"), run("sleep 100"), Entry("interrupt", "", REF))
    found = Loose.of(stopped)
    assert found is not None and found.ending == "interrupted"


def test_the_brief_keeps_only_this_project_and_counts_real_edits() -> None:
    edit = Entry("tool", "", REF, ToolCall("Edit", {"file_path": "/p/a.py"}))
    failed = Entry("tool", "", REF, ToolCall("Edit", {"file_path": "/p/b.py"}, is_error=True))
    here = session(ask("change a"), edit, failed, say("Done."))
    elsewhere = Session("o", "claude-code", Path("/other"), (ask("x"),))
    b = Brief.of([here, elsewhere], Path("/p"))
    assert [s.id for s in b.sessions] == ["s"]
    assert [(f.path, f.edits) for f in b.files] == [("a.py", 1)]
    assert b.last is not None and b.last.number == 1


def test_a_file_stack_has_one_layer_per_change_and_counts_failures() -> None:
    from matters.changes import Stack

    edit = Entry(
        "tool",
        "",
        REF,
        ToolCall("Edit", {"file_path": "/p/a.py", "old_string": "a\nb", "new_string": "a\nc\nd"}),
    )
    multi = Entry(
        "tool",
        "",
        REF,
        ToolCall(
            "MultiEdit", {"file_path": "/p/a.py", "edits": [{"old_string": "x", "new_string": ""}]}
        ),
    )
    failed = Entry("tool", "", REF, ToolCall("Edit", {"file_path": "/p/a.py"}, is_error=True))
    st = Stack.of([session(ask("go"), edit, ask("again"), multi, failed)], "/p/a.py")
    assert [(c.turn, c.added, c.removed) for c in st.changes] == [(1, 2, 1), (2, 0, 1)]
    assert st.failed == 1 and (st.added, st.removed) == (2, 2)
