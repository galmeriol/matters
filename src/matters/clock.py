"""Times as journals record them: ISO 8601 strings, read once into datetimes."""

import contextlib
from datetime import UTC, datetime

LIVE_SECONDS = 5 * 60  # quiet for longer than a long tool call or a long think: stopped


def moment(stamp: str | None) -> datetime | None:
    """The time a stamp names; None for no stamp or one that doesn't read as a time."""
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(stamp) if stamp else None
    return None


def seconds_between(start: datetime | None, end: datetime | None) -> float:
    """How long from start to end; nothing when either is unknown or end came first."""
    if start is None or end is None:
        return 0.0
    return max(0.0, (end - start).total_seconds())


def now() -> datetime:
    return datetime.now(UTC)


def is_recent(at: datetime | None, when: datetime, seconds: float = LIVE_SECONDS) -> bool:
    """Whether `at` was at most `seconds` before `when` (a minute ahead allows for skew)."""
    return at is not None and -60 <= (when - at).total_seconds() <= seconds
