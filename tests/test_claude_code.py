from pathlib import Path

import pytest

from matters.session import Session
from matters.sources.claude_code import ClaudeCode
from tests.fakes import FIXTURES

PROJECT = Path("/tmp/demo")


@pytest.fixture
def source() -> ClaudeCode:
    return ClaudeCode(root=FIXTURES / "claude")


@pytest.fixture
def session(source: ClaudeCode) -> Session:
    return next(s for s in source.sessions(PROJECT) if s.id == "s1")


def test_finds_one_projects_sessions_by_folder_name(source: ClaudeCode) -> None:
    assert [s.id for s in source.sessions(PROJECT)] == ["s1", "s2"]
    assert source.sessions(Path("/tmp/elsewhere")) == []


def test_finds_every_session_when_no_project_is_given(source: ClaudeCode) -> None:
    assert sorted(s.id for s in source.sessions()) == ["s1", "s2", "s3"]


def test_takes_the_project_from_the_recorded_working_directory(session: Session) -> None:
    assert session.project == PROJECT


def test_keeps_only_what_the_human_typed_as_asks(session: Session) -> None:
    assert [e.text for e in session.asks] == [
        "Add rate limiting to the login endpoint",
        "Also cover the signup endpoint\nwith the same limit",
    ]


def test_drops_injected_context_blocks_but_keeps_the_human_words(source: ClaudeCode) -> None:
    s2 = next(s for s in source.sessions(PROJECT) if s.id == "s2")
    assert s2.asks[-1].text == "Can we share one database across tests?"


def test_turns_each_content_block_into_one_entry(session: Session) -> None:
    assert [(e.kind, e.ref.line) for e in session.entries] == [
        ("ask", 2),
        ("thinking", 3),
        ("text", 3),
        ("tool", 3),
        ("command", 6),
        ("ask", 7),
        ("tool", 8),
        ("tool", 8),
        ("text", 10),
    ]


def test_pairs_tool_calls_with_their_results(session: Session) -> None:
    tools = [e.tool for e in session.entries if e.tool]
    assert [(t.name, t.result, t.is_error) for t in tools] == [
        ("Edit", "The file was updated.", False),
        ("Write", None, False),
        ("Edit", "old_string not found", True),
    ]


def test_knows_which_files_were_edited(session: Session) -> None:
    assert [f for e in session.entries for f in e.files] == [
        "/tmp/demo/app/login.rb",
        "/tmp/demo/app/signup.rb",
        "/tmp/demo/app/login.rb",
    ]


def test_uses_the_tools_own_title_and_timestamps(session: Session) -> None:
    assert session.headline == "Add login rate limit"
    assert (session.started_at, session.ended_at) == (
        "2026-11-10T09:00:00Z",
        "2026-11-10T09:02:30Z",
    )


def test_rereads_a_session_only_after_its_file_changes(tmp_path: Path) -> None:
    folder = tmp_path / "-p"
    folder.mkdir()
    log = folder / "s.jsonl"
    log.write_text('{"type":"user","cwd":"/p","message":{"content":"first"}}\n')
    source = ClaudeCode(root=tmp_path)
    assert source.sessions()[0] is source.sessions()[0]
    with log.open("a") as f:
        f.write('{"type":"user","message":{"content":"second"}}\n')
    assert [e.text for e in source.sessions()[0].asks] == ["first", "second"]


@pytest.fixture
def cli(source: ClaudeCode) -> Session:
    return source.sessions(Path("/tmp/cli"))[0]


def test_keeps_cli_context_as_parts_of_the_ask(cli: Session) -> None:
    ask = cli.asks[0]
    assert [(p.kind, p.label) for p in ask.parts] == [
        ("file", "Opened file"),
        ("selection", "app.py L3–5"),
        ("text", ""),
        ("pasted", "3 lines"),
        ("text", ""),
    ]
    assert ask.text == "here it is ; [Pasted text · 3 lines] what next?"


def test_slash_commands_are_events_with_their_output_attached(cli: Session) -> None:
    command = next(e for e in cli.entries if e.kind == "command")
    assert command.text == "/model opus"
    assert [(p.kind, p.text) for p in command.parts] == [("output", "Set model to opus")]


def test_attached_images_replace_their_text_markers(cli: Session) -> None:
    ask = cli.asks[1]
    assert [(p.kind, p.media_type) for p in ask.parts] == [("text", ""), ("image", "image/png")]


def test_interruptions_and_background_notices_are_events(cli: Session) -> None:
    turn = cli.turns[1]
    assert [(e.kind, e.text) for e in turn.events] == [
        ("interrupt", "Interrupted"),
        ("notice", "Tests finished"),
    ]
    assert [w.kind for w in turn.work] == ["tool"]


def test_messages_sent_mid_turn_are_asks_marked_as_queued(cli: Session) -> None:
    ask = cli.asks[-1]
    assert ask.text == "also check the logs"
    assert [p.kind for p in ask.parts] == ["queued", "text"]
    assert cli.turns[-1].answer is not None and cli.turns[-1].answer.text == "Logs are clean."


def test_a_model_call_split_over_records_is_counted_once(tmp_path: Path) -> None:
    """Claude Code writes one record per content block, each repeating the call's usage."""
    import json

    usage = {
        "input_tokens": 2,
        "output_tokens": 500,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 9000,
    }
    records = [
        {"type": "user", "timestamp": "2026-11-17T10:00:00Z", "cwd": "/tmp/t",
         "message": {"role": "user", "content": "go"}},
        {"type": "assistant", "timestamp": "2026-11-17T10:00:05Z",
         "message": {"id": "m1", "role": "assistant", "usage": {**usage, "output_tokens": 10},
                     "content": [{"type": "thinking", "thinking": "hmm"}]}},
        {"type": "assistant", "timestamp": "2026-11-17T10:00:09Z",
         "message": {"id": "m1", "role": "assistant", "usage": usage,
                     "content": [{"type": "text", "text": "done"}]}},
    ]  # fmt: skip
    folder = tmp_path / "-tmp-t"
    folder.mkdir()
    (folder / "x.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    (session,) = ClaudeCode(root=tmp_path).sessions()
    thinking, text = session.entries[1], session.entries[2]
    assert thinking.tokens is not None and text.tokens is None
    assert (thinking.tokens.output, thinking.tokens.cache_read) == (500, 9000)  # the final usage
    assert thinking.tokens.total == 9602


def test_a_compaction_summary_is_a_notice_not_an_ask(tmp_path: Path) -> None:
    """When the context fills up, Claude Code writes its summary as a user record."""
    import json

    summary = "This session is being continued from a previous conversation.\n- the user asked X"
    records = [
        {"type": "user", "cwd": "/tmp/t", "message": {"role": "user", "content": "build X"}},
        {"type": "user", "cwd": "/tmp/t", "isCompactSummary": True,
         "message": {"role": "user", "content": summary}},
        {"type": "user", "cwd": "/tmp/t", "message": {"role": "user", "content": "now Y"}},
    ]  # fmt: skip
    folder = tmp_path / "-tmp-t"
    folder.mkdir()
    (folder / "x.jsonl").write_text("\n".join(json.dumps(r) for r in records))
    (session,) = ClaudeCode(root=tmp_path).sessions()
    assert [a.text for a in session.asks] == ["build X", "now Y"]
    notice = session.entries[1]
    assert notice.kind == "notice" and notice.parts[0].text == summary
    assert len(session.turns) == 2
