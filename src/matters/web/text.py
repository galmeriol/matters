"""Words and numbers as the pages print them: clipped titles, times in local time,
durations and counts in a few characters."""

import re
from datetime import datetime
from html import escape

from matters.clock import moment


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def clip(text: str, limit: int) -> str:
    """One line, at most `limit` characters, an ellipsis where it was cut."""
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def breakable(path: str) -> str:
    """A path that wraps after its slashes, not in the middle of a name (HTML)."""
    return escape(path).replace("/", "/<wbr>")


def unbroken(text: str) -> str:
    """Kept on one line: a duration split over two reads as two numbers."""
    return text.replace(" ", "\u00a0")


def plural(n: int, word: str) -> str:
    """'1 tool call', '3 tool calls'."""
    return f"{n} {word}{'s' if n != 1 else ''}"


def when(stamp: str | None) -> str:
    at = moment(stamp)
    return at.astimezone().strftime("%Y-%m-%d %H:%M") if at else "undated"


def clock(stamp: str | None) -> str:
    at = moment(stamp)
    return f"{at.astimezone():%H:%M}" if at else ""


def short_date(stamp: str | None) -> str:
    at = moment(stamp)
    return at.astimezone().strftime("%d %b") if at else "—"


def span(start: datetime | None, end: datetime | None) -> str:
    """When something ran, start to end, in local time: the end's date only if it differs."""
    if not start:
        return "undated"
    a = start.astimezone()
    if not end or end <= start:
        return f"{a:%d %b %Y %H:%M}"
    b = end.astimezone()
    return f"{a:%d %b %Y %H:%M} – " + (f"{b:%H:%M}" if a.date() == b.date() else f"{b:%d %b %H:%M}")


def ago(seconds: float) -> str:
    """How long ago, roughly: 'just now', '40 s ago', '3 min ago', '2 h 5 min ago'."""
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)} s ago"
    if seconds < 3600:
        return f"{seconds // 60:.0f} min ago"
    return f"{seconds // 3600:.0f} h {seconds % 3600 // 60:.0f} min ago"


def count(n: int) -> str:
    """A count in at most four characters: 950, 1.2k, 18k, 3.4M."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k" if n >= 10_000 else f"{n / 1_000:.1f}k"
    return str(n)


def duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


def short_duration(seconds: float) -> str:
    """For a chart's columns and ticks: '8s', '18m', '2h 27m'."""
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = round(seconds / 60)
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m"


def minutes(seconds: float) -> str:
    """A whole session's length: '45 min', '2 h 5 min'."""
    whole = int(seconds // 60)
    return f"{whole // 60} h {whole % 60} min" if whole >= 60 else f"{whole} min"


def milliseconds(ms: int) -> str:
    """A run's length, with a decimal while it is short: '2.7 s', '64 s', '10 min'."""
    seconds = ms / 1000
    if seconds < 10:
        return f"{seconds:.1f} s"
    if seconds < 90:
        return f"{seconds:.0f} s"
    mins = seconds / 60
    return f"{mins:.0f} min" if mins < 90 else f"{mins // 60:.0f} h {mins % 60:02.0f}"


def model_name(model: str) -> str:
    """'claude-haiku-5-5' -> 'Haiku 5.5'; a dated id loses its date."""
    if not model.startswith("claude-"):
        return model
    words = [w for w in model.removeprefix("claude-").split("-") if not re.fullmatch(r"\d{8}", w)]
    names = [w.capitalize() for w in words if not w.isdigit()]
    version = ".".join(w for w in words if w.isdigit())
    return " ".join([*names, version]).strip()
