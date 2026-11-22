"""Claude Code's sessions, read from its journals on disk.

~/.claude/projects/<project path, non-alphanumerics as "-">/<session id>.jsonl, one JSON
record per line; a session's subagents keep their own journals in a folder beside it.
"""

import re
from pathlib import Path

from matters.session import Session
from matters.sources.claude_agents import AGENT_TOOLS, AgentFile, Notices, last_changed, runs
from matters.sources.claude_records import Journal


class ClaudeCode:
    """Parsed sessions are cached per file until it (or one of its subagents) changes, so
    a long-running viewer only re-reads sessions that grew."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".claude" / "projects"
        self._cache: dict[Path, tuple[tuple[int, ...], Session]] = {}

    def sessions(self, project: Path | None = None) -> list[Session]:
        folders = "*" if project is None else re.sub(r"[^A-Za-z0-9]", "-", str(project))
        sessions = (self._load(path) for path in sorted(self.root.glob(f"{folders}/*.jsonl")))
        return [s for s in sessions if not s.is_empty and (project is None or s.project == project)]

    def _load(self, path: Path) -> Session:
        stamp = last_changed(path)
        cached = self._cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        session = read_session(path)
        self._cache[path] = (stamp, session)
        return session


def read_session(path: Path) -> Session:
    """A session's journal, with the subagents it started."""
    journal = Journal.read(path)
    calls = journal.calls_to(AGENT_TOOLS)
    notices = Notices.from_records(list(journal.records))
    agents = runs(calls, AgentFile.all_beside(path), notices)
    return journal.to_session(path, tuple(agents))
