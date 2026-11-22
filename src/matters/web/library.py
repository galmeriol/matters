from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

from matters.knowledge.model import Item
from matters.session import Session


@dataclass(frozen=True, slots=True)
class Library:
    """Every session, and what was learned from them: what the rail and every page draw
    from, so any page can link to the others (a turn to the knowledge it became, a
    project to its sessions, a knowledge item to its turn)."""

    sessions: list[Session]
    knowledge: tuple[Item, ...] = ()

    def session(self, session_id: str) -> Session | None:
        return next((s for s in self.sessions if s.id == session_id), None)

    def projects(self) -> dict[Path, list[Session]]:
        """Projects by their latest activity, each with its sessions newest first."""
        grouped: dict[Path, list[Session]] = defaultdict(list)
        for session in by_recency(self.sessions):
            grouped[session.project].append(session)
        return dict(grouped)

    def project_named(self, name: str) -> Path | None:
        return next((p for p in self.projects() if project_key(p) == name), None)

    def learned_in(self, session_id: str) -> dict[int, list[Item]]:
        """Turn -> the knowledge that cites it (accepted or waiting for review)."""
        found: dict[int, list[Item]] = defaultdict(list)
        for item in self.knowledge:
            if item.status == "rejected":
                continue
            for turn in item.turns_in(session_id):
                found[turn].append(item)
        return dict(found)

    @property
    def to_review(self) -> int:
        return sum(1 for i in self.knowledge if i.status == "candidate")


def by_recency(sessions: list[Session]) -> list[Session]:
    return sorted(sessions, key=lambda s: s.ended_at or s.started_at or "", reverse=True)


def project_key(project: Path) -> str:
    return project.name or str(project)


def project_href(project: Path) -> str:
    return f"/p/{quote(project_key(project), safe='')}"


def knowledge_href(item: Item) -> str:
    view = {"accepted": "accepted", "rejected": "rejected"}.get(item.status, "")
    return href("/knowledge", view=view) + f"#k{item.id}"


def file_href(path: str, session: Session | None = None, turn: int = 0) -> str:
    """A file's stack of changes: in one session, or (no session) in all of them."""
    link = href("/f", path=path, s=session.id if session else "")
    return link + (f"#{layer_id(session, turn)}" if session and turn else "")


def agent_href(session: Session, agent_id: str) -> str:
    """A subagent's run: its prompt, every step it took, and what it reported."""
    return f"/s/{quote(session.id)}/agents/{quote(agent_id)}"


def layer_id(session: Session, turn: int) -> str:
    """The anchor of the first layer a turn added to a stack."""
    return f"L-{session.id}-{turn}"


def href(path: str, /, **params: str) -> str:
    """A link that keeps only the parameters that are set."""
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{path}?{query}" if query else path
