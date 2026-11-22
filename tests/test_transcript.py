"""What a model reads: selected sessions as a compact, citable, redacted transcript."""

from pathlib import Path

import pytest

from matters.redact import MARK, redact
from matters.session import Entry, Session, SourceRef
from matters.sources.claude_code import ClaudeCode
from matters.transcript import Transcript
from tests.fakes import FIXTURES


def sessions() -> list[Session]:
    return ClaudeCode(root=FIXTURES / "claude").sessions()


def by_id(session_id: str) -> Session:
    return next(s for s in sessions() if s.id == session_id)


def test_transcript_names_sessions_oldest_first_and_numbers_turns_like_the_page() -> None:
    s1, s3 = by_id("s1"), by_id("s3")
    transcript = Transcript.build([s3, s1])
    assert list(transcript.aliases.values()) == sorted(
        [s1.id, s3.id], key=lambda sid: by_id(sid).started_at or ""
    )
    assert transcript.turns["s1"] == len(s1.turns)
    assert '<session id="S1"' in transcript.text
    assert '<turn n="1">' in transcript.text
    assert "<human>Add rate limiting to the login endpoint</human>" in transcript.text
    assert "- Edit: /tmp/demo/app/login.rb" in transcript.text
    assert transcript.clipped == ()


def test_transcript_leaves_out_thinking_and_reminders() -> None:
    text = Transcript.build([by_id("s1"), by_id("s3")]).text
    assert "token bucket per IP is enough" not in text  # s1's thinking
    assert "system-reminder" not in text


def test_transcript_shortens_to_the_budget_and_says_so() -> None:
    full = Transcript.build([by_id("s3")])
    small = Transcript.build([by_id("s3")], limit=len(full.text) // 2)
    assert len(small.text) < len(full.text)
    assert small.clipped, "shortening must be reported"


def test_transcript_cut_beyond_the_budget_is_reported() -> None:
    cut = Transcript.build([by_id("s3")], limit=200)
    assert cut.text.endswith("[TRANSCRIPT CUT HERE]")
    assert any("larger than the budget" in note for note in cut.clipped)


def test_secrets_are_redacted_before_the_model_sees_them() -> None:
    ask = Entry(
        "ask",
        "deploy with ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnop",
        SourceRef(Path("x"), 1),
    )
    session = Session("x", "claude-code", Path("/tmp/x"), (ask,))
    text = Transcript.build([session]).text
    assert "sk-ant" not in text
    assert MARK in text


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA",
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_abcdefghijklmnopqrstuvwxyz0123",
        "password: hunter2hunter2",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "https://user:pa55word@example.com/repo.git",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_redact_masks_common_credentials(secret: str) -> None:
    masked = redact(f"before {secret} after")
    assert MARK in masked
    assert "before" in masked and "after" in masked


def test_redact_leaves_ordinary_prose_alone() -> None:
    prose = "We decided the token bucket is enough; the password form stays as it is."
    assert redact(prose) == prose
