"""Everything that needs a model, in one place for the viewer: extracting knowledge, its
store, the provider it uses, and the background jobs that run it. Extraction reads the
instruction files you already keep, so it proposes only what they don't say yet."""

from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from matters.jobs import Jobs
from matters.knowledge import instructions
from matters.knowledge.extractor import Extractor, LlmExtractor
from matters.knowledge.store import Added, KnowledgeStore
from matters.llm import Provider
from matters.session import Session
from matters.transcript import Transcript


def selection_key(session_ids: list[str]) -> str:
    """The same sessions in any order are the same selection."""
    return ",".join(sorted(set(session_ids)))


def review_url(added: Added) -> str:
    """Where to review what an extraction found: the review list, saying what it found,
    with the new items and the known ones it added evidence to marked."""
    ids = {"new": added.new, "merged": added.merged}
    params = {"extracted": "1"} | {k: ",".join(map(str, v)) for k, v in ids.items() if v}
    return "/knowledge?" + urlencode(params, safe=",")


class Workbench:
    def __init__(
        self,
        provider: Provider,
        database: Path,
        *,
        extractor: Extractor | None = None,
        jobs: Jobs | None = None,
        home: Path | None = None,
    ) -> None:
        self.provider = provider
        self.extractor = extractor or LlmExtractor(provider)
        self.knowledge = KnowledgeStore(database)
        self.jobs = jobs or Jobs()
        self.home = home  # where ~/.claude/CLAUDE.md is looked for; None: the real home

    def ready(self) -> bool:
        return self.provider.configured()

    def extract(self, sessions: list[Session]) -> str:
        """Start proposing preferences and facts from these sessions; the URL of the job.
        What comes back waits in the review list."""
        projects = {s.id: str(s.project) for s in sessions}
        text = replace(
            Transcript.build(sessions),
            written=instructions.written(projects.values(), self.home),
        )
        ids = [s.id for s in sessions]

        def work() -> str:
            extracted = self.extractor.extract(text, self.knowledge.all(), projects)
            added = self.knowledge.add(extracted.drafts, extracted.usage.model)
            self.knowledge.read(sessions)
            return review_url(added)

        job = self.jobs.start(
            f"knowledge:{selection_key(ids)}",
            "Extracting preferences and facts",
            work,
            session_ids=tuple(sorted(ids)),
            detail=f"about {text.tokens:,} tokens in",
            retry=("/knowledge/extract", {"s": ids}),
        )
        return f"/jobs/{job.id}"
