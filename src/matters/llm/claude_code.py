"""Provider adapter for Claude through the local Claude Code CLI, run headless.

Whoever reads their Claude Code sessions already has `claude` installed and signed in,
so this needs no key and no other account. Each request is one `claude -p` run:

- `--no-session-persistence`: the run leaves no session file, so it never shows up
  among the sessions matters reads.
- `--restricted --tools ""`: no tools, and the user's settings files (hooks among
  them) are ignored; sign-in still works, unlike `--bare`.
- `--system-prompt` replaces Claude Code's own, `--json-schema` validates the answer,
  which comes back in the result's `structured_output`.
- The transcript goes in on stdin; it can be far larger than a command line allows.

Runs start in one folder of matters' own, because Claude Code keeps a (mostly empty)
project folder for every working directory it is started in.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from matters.errors import ModelError
from matters.llm import Completion, Effort, Usage
from matters.paths import state_dir

TIMEOUT = 30 * 60  # seconds: a large selection at high effort takes minutes


class ClaudeCodeProvider:
    name = "claude"
    setup_hint = (
        'Install <a href="https://docs.claude.com/en/docs/claude-code">Claude Code</a> and sign in'
        " by running <code>claude</code> once"
    )

    def __init__(
        self,
        model: str | None = None,
        effort: Effort = "high",
        *,
        command: str = "claude",
        workdir: Path | None = None,
    ) -> None:
        self._model = model
        self.effort = effort
        self.command = command
        self.workdir = workdir

    @property
    def model(self) -> str:
        """The model asked for; empty means Claude Code's own default."""
        return self._model or ""

    def configured(self) -> bool:
        return shutil.which(self.command) is not None

    def complete_json(
        self, system: str, user: str, schema: dict[str, Any], *, max_tokens: int
    ) -> Completion:
        # max_tokens has no CLI flag: Claude Code sizes the answer itself.
        executable = shutil.which(self.command)
        if executable is None:
            raise ModelError("Claude Code isn't installed: install it and sign in with `claude`.")
        args = [
            executable,
            "-p",
            "--no-session-persistence",
            "--restricted",
            "--tools",
            "",
            "--output-format",
            "json",
            "--system-prompt",
            system,
            "--json-schema",
            json.dumps(schema),
            "--effort",
            self.effort,
        ]
        if self._model:
            args += ["--model", self._model]
        workdir = self.workdir or state_dir() / "claude"
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            run = subprocess.run(
                args,
                input=user,
                capture_output=True,
                text=True,
                cwd=workdir,
                timeout=TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ModelError(f"Claude didn't answer within {TIMEOUT // 60} minutes.") from error
        except OSError as error:
            raise ModelError(f"Couldn't run Claude Code: {error}") from error
        return _completion(run, self.model)


def _completion(run: subprocess.CompletedProcess[str], asked: str) -> Completion:
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict):
        said = (run.stderr or run.stdout).strip().splitlines()
        raise ModelError(f"Claude Code failed: {said[-1] if said else f'exit {run.returncode}'}")
    usage = _usage(result, asked)
    if result.get("is_error") or run.returncode:
        reason = str(result.get("result") or "").strip() or f"exit {run.returncode}"
        if "refus" in reason.lower() or result.get("stop_reason") == "refusal":
            raise ModelError(f"Claude declined to answer: {reason}")
        raise ModelError(f"Claude Code: {reason}")
    data = result.get("structured_output")
    if not isinstance(data, dict):
        raise ModelError("Claude didn't return the JSON that was asked for.")
    return Completion(data, usage)


def _usage(result: dict[str, Any], asked: str) -> Usage:
    """Tokens of the model that answered; cache reads and writes count as input."""
    models = result.get("modelUsage")
    if not isinstance(models, dict) or not models:
        return Usage(asked or "claude")
    model, counts = max(models.items(), key=lambda item: item[1].get("outputTokens", 0))
    input_tokens = sum(
        int(counts.get(key, 0))
        for key in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
    )
    return Usage(model, input_tokens, int(counts.get("outputTokens", 0)))
