"""The one SQLite file matters keeps (knowledge), opened per use.

A connection per call: requests and background jobs run on different threads.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        yield db
