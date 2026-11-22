"""Model calls run in the background; the page polls the job until it's done.

A job is any piece of work that ends at a page (`work()` returns its URL).
Jobs live in memory only: a restart forgets running jobs, never their results.
Asking again for work with the same key while it runs returns the running job.
"""

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from matters.errors import MattersError

type State = Literal["running", "done", "failed"]


@dataclass(slots=True)
class Job:
    id: int
    key: str
    title: str
    session_ids: tuple[str, ...] = ()
    detail: str = ""
    started: float = field(default_factory=time.monotonic)
    state: State = "running"
    result_url: str = ""
    error: str = ""
    retry: tuple[str, dict[str, list[str]]] | None = None  # (path, form) that starts it again

    @property
    def elapsed(self) -> int:
        return int(time.monotonic() - self.started)


class Jobs:
    def __init__(self, *, synchronous: bool = False) -> None:
        """synchronous: run each job before `start` returns (tests)."""
        self.synchronous = synchronous
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def start(self, job_key: str, title: str, work: Callable[[], str], **about: object) -> Job:
        with self._lock:
            running = next(
                (j for j in self._jobs.values() if j.state == "running" and j.key == job_key), None
            )
            if running:
                return running
            job = Job(next(self._ids), job_key, title, **about)  # type: ignore[arg-type]
            self._jobs[job.id] = job
        if self.synchronous:
            self._run(job, work)
        else:
            threading.Thread(
                target=self._run, args=(job, work), name=f"job-{job.id}", daemon=True
            ).start()
        return job

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def _run(self, job: Job, work: Callable[[], str]) -> None:
        try:
            job.result_url = work()
            job.state = "done"
        except MattersError as error:
            job.error, job.state = str(error), "failed"
        except Exception as error:  # a background thread must always report back
            job.error, job.state = f"Unexpected error: {error!r}", "failed"
