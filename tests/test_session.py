from pathlib import Path

from matters.session import Entry, Session, SourceRef, ToolCall

REF = SourceRef(Path("s.jsonl"), 1)


def entry(kind: str, text: str = "", tool: str | None = None) -> Entry:
    return Entry(kind, text, REF, ToolCall(tool) if tool else None)  # type: ignore[arg-type]


def session(*entries: Entry) -> Session:
    return Session(id="s", provider="tool", project=Path("/p"), entries=entries)


def test_groups_entries_into_turns_starting_at_each_ask() -> None:
    turns = session(
        entry("ask", "one"), entry("text", "a"), entry("ask", "two"), entry("tool", tool="Bash")
    ).turns
    assert [(t.ask.text if t.ask else None, len(t.steps)) for t in turns] == [
        ("one", 1),
        ("two", 1),
    ]


def test_keeps_work_that_happened_before_any_ask() -> None:
    turns = session(entry("text", "resumed"), entry("ask", "go")).turns
    assert [t.ask.text if t.ask else None for t in turns] == [None, "go"]


def test_the_answer_is_the_last_text_and_the_rest_is_work() -> None:
    turn = session(
        entry("ask", "q"),
        entry("text", "looking"),
        entry("tool", tool="Read"),
        entry("text", "done"),
        entry("thinking", "hm"),
    ).turns[0]
    assert turn.answer is not None
    assert turn.answer.text == "done"
    assert [s.kind for s in turn.work] == ["text", "tool", "thinking"]


def test_counts_tools_most_used_first() -> None:
    turn = session(
        entry("ask", "q"),
        entry("tool", tool="Read"),
        entry("tool", tool="Bash"),
        entry("tool", tool="Bash"),
    ).turns[0]
    assert turn.tool_counts == {"Bash": 2, "Read": 1}


def test_only_edit_tools_report_edited_files() -> None:
    assert ToolCall("Edit", {"file_path": "a.py"}).edited_file == "a.py"
    assert ToolCall("Read", {"file_path": "a.py"}).edited_file is None


def test_events_are_shown_beside_the_turn_never_folded_into_work() -> None:
    turn = session(
        entry("ask", "q"),
        entry("tool", tool="Bash"),
        entry("interrupt", "Interrupted"),
        entry("text", "ok"),
    ).turns[0]
    assert [e.kind for e in turn.events] == ["interrupt"]
    assert [w.kind for w in turn.work] == ["tool"]
