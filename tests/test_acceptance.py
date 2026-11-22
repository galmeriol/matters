"""The one behaviour every iteration must preserve: "where does this project stand?",
answered from the sessions on disk, every line traceable to its source."""

from pathlib import Path

from matters.brief import Brief
from matters.sources.claude_code import ClaudeCode
from tests.fakes import FIXTURES

CLAUDE = FIXTURES / "claude" / "-tmp-demo"


def test_briefs_a_project_from_its_claude_code_sessions() -> None:
    expected = f"""\
# demo

/tmp/demo · 2 sessions · 2026-11-01 – 2026-11-10

## Where you left off

[Add login rate limit](vscode://file{CLAUDE}/s1.jsonl:2) · turn 2

> Also cover the signup endpoint
> with the same limit

Both endpoints are now limited.

Resume: `cd /tmp/demo && claude --resume s1`

## Still open

- No answer: [Can we share one database across tests?](vscode://file{CLAUDE}/s2.jsonl:3) (Why is the test suite slow?)

## Files touched

- [app/signup.rb](vscode://file/tmp/demo/app/signup.rb) · 1 edit · last in [Add login rate limit](vscode://file{CLAUDE}/s1.jsonl:8), turn 2
- [app/login.rb](vscode://file/tmp/demo/app/login.rb) · 1 edit · last in [Add login rate limit](vscode://file{CLAUDE}/s1.jsonl:3), turn 1

## Sessions

- 2026-11-10 [Add login rate limit](vscode://file{CLAUDE}/s1.jsonl:2) · 2 asks
- 2026-11-01 [Why is the test suite slow?](vscode://file{CLAUDE}/s2.jsonl:1) · 2 asks
"""
    sessions = ClaudeCode(root=FIXTURES / "claude").sessions(Path("/tmp/demo"))
    assert Brief.of(sessions, Path("/tmp/demo")).to_markdown() == expected
