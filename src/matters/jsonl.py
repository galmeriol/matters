import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def json_lines(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (1-based line number, record) for each JSON object line.

    Lines that don't parse are skipped: the last line of a session that is
    still being written is often incomplete.
    """
    with path.open(encoding="utf-8") as lines:
        for line, raw in enumerate(lines, start=1):
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield line, record
