"""The one provider: Claude through a headless `claude -p` run. A fake `claude` script stands
in for the CLI, so the real subprocess path runs and no model is ever called."""

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from matters.errors import ModelError, SettingError
from matters.llm.claude_code import ClaudeCodeProvider
from matters.llm.registry import from_env

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}

ANSWER = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": '{"a": 1}',
    "structured_output": {"a": 1},
    "modelUsage": {
        "claude-sonnet-5-5": {
            "inputTokens": 7,
            "outputTokens": 40,
            "cacheReadInputTokens": 100,
            "cacheCreationInputTokens": 1000,
        },
        "claude-haiku-5-5": {"inputTokens": 3, "outputTokens": 2},
    },
}


def fake_claude(folder: Path, stdout: str, *, exit_code: int = 0, stderr: str = "") -> Path:
    """A `claude` that records its arguments, stdin and working folder, then prints `stdout`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "stdout").write_text(stdout)
    (folder / "stderr").write_text(stderr)
    script = folder / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "here = pathlib.Path(__file__).parent\n"
        "(here / 'called.json').write_text(json.dumps("
        "{'args': sys.argv[1:], 'stdin': sys.stdin.read(), 'cwd': os.getcwd()}))\n"
        "sys.stdout.write((here / 'stdout').read_text())\n"
        "sys.stderr.write((here / 'stderr').read_text())\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def called(script: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((script.parent / "called.json").read_text())
    return result


def provider(script: Path, tmp_path: Path, model: str | None = None) -> ClaudeCodeProvider:
    return ClaudeCodeProvider(model, "low", command=str(script), workdir=tmp_path / "work")


def test_a_request_is_one_headless_run_that_leaves_no_session(tmp_path: Path) -> None:
    script = fake_claude(tmp_path / "bin", json.dumps(ANSWER))
    completion = provider(script, tmp_path, "sonnet").complete_json(
        "be brief", "the transcript", SCHEMA, max_tokens=10
    )
    assert completion.data == {"a": 1}
    # The model that did the work; cache reads and writes count as input.
    assert completion.usage.model == "claude-sonnet-5-5"
    assert (completion.usage.input_tokens, completion.usage.output_tokens) == (1107, 40)
    run = called(script)
    args = run["args"]
    assert args[0] == "-p" and "--no-session-persistence" in args and "--restricted" in args
    assert args[args.index("--tools") + 1] == ""  # no tools at all
    assert args[args.index("--system-prompt") + 1] == "be brief"
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--effort") + 1] == "low"
    assert run["stdin"] == "the transcript"  # never on the command line: it can be huge
    assert Path(run["cwd"]).resolve() == (tmp_path / "work").resolve()


def test_without_a_model_claude_code_picks_its_own(tmp_path: Path) -> None:
    script = fake_claude(tmp_path / "bin", json.dumps(ANSWER))
    provider(script, tmp_path).complete_json("s", "u", SCHEMA, max_tokens=10)
    assert "--model" not in called(script)["args"]


def test_an_error_result_is_passed_on_in_claude_codes_words(tmp_path: Path) -> None:
    failed = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    script = fake_claude(tmp_path / "bin", json.dumps(failed), exit_code=1)
    with pytest.raises(ModelError, match="Not logged in"):
        provider(script, tmp_path).complete_json("s", "u", SCHEMA, max_tokens=10)


def test_a_refusal_is_a_declined_error(tmp_path: Path) -> None:
    refused = {"type": "result", "is_error": True, "stop_reason": "refusal", "result": "No."}
    script = fake_claude(tmp_path / "bin", json.dumps(refused))
    with pytest.raises(ModelError, match="declined"):
        provider(script, tmp_path).complete_json("s", "u", SCHEMA, max_tokens=10)


def test_output_that_isnt_a_result_says_what_the_cli_said(tmp_path: Path) -> None:
    script = fake_claude(tmp_path / "bin", "", exit_code=2, stderr="error: unknown option\n")
    with pytest.raises(ModelError, match="unknown option"):
        provider(script, tmp_path).complete_json("s", "u", SCHEMA, max_tokens=10)


def test_an_answer_without_structured_output_is_an_error(tmp_path: Path) -> None:
    answer = {**ANSWER, "structured_output": None}
    script = fake_claude(tmp_path / "bin", json.dumps(answer))
    with pytest.raises(ModelError, match="JSON"):
        provider(script, tmp_path).complete_json("s", "u", SCHEMA, max_tokens=10)


def test_configured_means_claude_is_on_the_path(tmp_path: Path) -> None:
    script = fake_claude(tmp_path / "bin", "{}")
    assert ClaudeCodeProvider(command=str(script)).configured()
    missing = ClaudeCodeProvider(command=str(tmp_path / "nowhere" / "claude"))
    assert not missing.configured()
    with pytest.raises(ModelError, match="isn't installed"):
        missing.complete_json("s", "u", SCHEMA, max_tokens=10)


def test_model_and_effort_come_from_the_environment() -> None:
    chosen = from_env({"MATTERS_MODEL": "opus", "MATTERS_EFFORT": "max"})
    assert isinstance(chosen, ClaudeCodeProvider)
    assert (chosen.model, chosen.effort) == ("opus", "max")
    default = from_env({})
    assert isinstance(default, ClaudeCodeProvider)
    assert (default.model, default.effort) == ("", "high")


def test_an_unknown_effort_is_refused() -> None:
    with pytest.raises(SettingError, match="low, medium, high, xhigh, max"):
        from_env({"MATTERS_EFFORT": "extreme"})
