"""The provider, from the environment. There is one: Claude, through the local Claude Code CLI.

MATTERS_MODEL    a model or alias Claude Code accepts, e.g. sonnet, opus   (optional;
                 default: Claude Code's own default model)
MATTERS_EFFORT   low | medium | high | xhigh | max                      (default high)
"""

import os
from collections.abc import Mapping

from matters.errors import SettingError
from matters.llm import EFFORTS, Provider
from matters.llm.claude_code import ClaudeCodeProvider


def from_env(environ: Mapping[str, str] | None = None) -> Provider:
    env = os.environ if environ is None else environ
    model = env.get("MATTERS_MODEL", "").strip() or None
    effort_text = env.get("MATTERS_EFFORT", "").strip().lower() or "high"
    effort = next((e for e in EFFORTS if e == effort_text), None)
    if effort is None:
        allowed = ", ".join(EFFORTS)
        raise SettingError(f"MATTERS_EFFORT must be one of {allowed}, not {effort_text!r}.")
    return ClaudeCodeProvider(model, effort)
