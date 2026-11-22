"""What the developer has already written down for assistants: CLAUDE.md, AGENTS.md and
exported PREFERENCES.md / FACTS.md, globally and in each project. Extraction reads them
so it doesn't propose again what is already a rule. Read only; secrets redacted."""

from collections.abc import Iterable
from html import escape
from pathlib import Path

from matters.redact import redact

NAMES = ("CLAUDE.md", "AGENTS.md", "PREFERENCES.md", "FACTS.md")
PER_FILE = 12_000  # characters
TOTAL = 60_000


def candidates(projects: Iterable[str], home: Path) -> list[Path]:
    places = [home / ".claude"]
    for project in dict.fromkeys(projects):
        places += [Path(project), Path(project) / ".claude"]
    return [place / name for place in places for name in NAMES]


def written(projects: Iterable[str], home: Path | None = None) -> str:
    """The files that exist, as <file path="…"> blocks, shortened to fit."""
    blocks: list[str] = []
    used = 0
    for path in candidates(projects, home or Path.home()):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        text = text[:PER_FILE]
        if used + len(text) > TOTAL:
            break
        used += len(text)
        body = escape(redact(text), quote=False)
        blocks.append(f'<file path="{escape(str(path))}">\n{body}\n</file>')
    return "\n".join(blocks)
