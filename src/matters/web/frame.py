"""What every page shares: the document around it, and the session rail on its left, so
moving between projects and sessions never needs a trip back to an index page."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from html import escape
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from matters.brief import Loose
from matters.clock import now
from matters.session import Session
from matters.timeline import Timeline
from matters.web.icons import FAVICON, SPRITE, icon, mark
from matters.web.library import Library, by_recency, project_href, project_key
from matters.web.orders import ORDERS
from matters.web.text import clip, first_line, minutes, plural, short_date, short_duration

STYLE = files("matters.web").joinpath("style.css").read_text(encoding="utf-8")
SCRIPT = files("matters.web").joinpath("viewer.js").read_text(encoding="utf-8")

# (value, name, what it looks like); the first is the default.
THEMES = (
    ("paper", "Paper", "Ink on neutral paper"),
    ("warm", "Warm", "Cream paper, ink blue"),
    ("library", "Library", "Green rail, warm paper"),
)
MODES = (("auto", "Auto"), ("light", "Light"), ("dark", "Dark"))
# What you left set, applied before the page paints so it never flashes the default: the
# theme and mode, the timeline's lanes when you closed them, and its marks shaded by token
# use (a long page is drawn long before the script at its end runs).
REMEMBERED = (
    "<script>try{const d=document.documentElement;"
    'for(const k of["theme","mode"]){const v=localStorage.getItem("matters-"+k);if(v)d.dataset[k]=v}'
    'if(localStorage.getItem("matters.timeline")==="closed")d.dataset.timeline="closed";'
    'if(localStorage.getItem("matters.shade")==="tokens")d.dataset.shade="tokens"'
    "}catch(e){}</script>"
)
RECENT = timedelta(days=7)  # a project with a session this recent starts unfolded
# The projects you folded or unfolded yourself, applied as soon as the rail is parsed, so it
# never shows the default first. Your fold wins, even on the project you are reading.
KEPT_FOLDS = (
    'try{const k=JSON.parse(localStorage.getItem("matters.rail")||"{}");'
    'for(const g of document.querySelectorAll("details.group"))'
    "if(g.dataset.key in k)g.open=k[g.dataset.key]"
    "}catch(e){}"
)


def layout(title: str, rail: str, main: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(clip(first_line(title), 60))} · matters</title>
{REMEMBERED}
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<style>{STYLE}</style></head>
<body>{SPRITE}
<div class="loading-bar" aria-hidden="true"></div>
<button type="button" class="rail-toggle" aria-label="Sessions">{icon("menu")}</button>
<div class="frame">{rail}<main class="page">{main}</main></div>
<script>{SCRIPT}</script></body></html>"""


def rail(library: Library, here: str, current: Session | None = None, query: str = "") -> str:
    """Every session by project, newest activity first, set like a book's contents: a
    project is a part (its name opens its brief), a session a line with its work time
    where a page number would be. A ring marks a session that ended unfinished, a pulse
    one still being written. A project folds; it starts open while it is recent."""
    at = now()
    groups = "".join(
        _rail_group(project, sessions, current, here, at)
        for project, sessions in library.projects().items()
    )
    review = (
        f'<span class="n" title="waiting for review">{library.to_review}</span>'
        if library.to_review
        else ""
    )
    return f"""
<nav class="rail" aria-label="Sessions">
  <div class="rail-head">
    <div class="rail-top"><a class="wordmark" href="/">{mark()}matters</a>{appearance()}</div>
    <form class="filter" action="/search" method="get" role="search">
      {icon("search")}<input type="search" name="q" value="{escape(query)}" placeholder="Filter · Enter searches all text"
        aria-label="Filter sessions, or press Enter to search everything" autocomplete="off">
    </form>
    <p class="rail-links"><a class="rail-link{" on" if here.startswith("/knowledge") else ""}" href="/knowledge">{icon("bulb")}Knowledge{review}</a></p>
  </div>
  <div class="rail-list"><p class="contents">Contents</p>{groups}</div>
</nav>
<script>{KEPT_FOLDS}</script>"""


def appearance() -> str:
    """The theme, light or dark, and the order every session's turns read in, behind a
    button at the top of the rail. Kept in the browser by the page script, which also
    shows the button: without it nothing applies."""
    themes = "".join(
        f'<label><input type="radio" name="theme" value="{value}">'
        f'<span class="swatch {value}" aria-hidden="true"><i></i><i></i><i></i></span>'
        f"<span>{name}<small>{note}</small></span></label>"
        for value, name, note in THEMES
    )
    modes = "".join(
        f'<label><input type="radio" name="mode" value="{value}"><span>{name}</span></label>'
        for value, name in MODES
    )
    orders = "".join(
        f'<label><input type="radio" name="order" value="{value}"><span>{name}</span></label>'
        for value, name in ORDERS
    )
    return f"""<details class="settings" hidden><summary title="Settings" aria-label="Settings">{icon("sliders")}</summary>
  <div class="settings-menu"><fieldset class="themes"><legend>Theme</legend>{themes}</fieldset>
  <fieldset class="modes"><legend>Mode</legend><div class="segmented">{modes}</div></fieldset>
  <fieldset class="orders"><legend>Turns</legend><div class="segmented">{orders}</div>
  <p class="settings-note">For every session, unless you set one on its page.</p></fieldset></div></details>"""


def sessions_list(sessions: Sequence[Session], current: Session | None = None) -> str:
    """Sessions as rows of a ledger: date, title, size, how it ended."""
    rows, at = [], now()
    for s in by_recency(list(sessions)):
        loose = Loose.of(s)
        end = f'<span class="badge {loose.ending}">{escape(loose.ending)}</span>' if loose else ""
        if s.is_live(at):
            end = '<span class="badge running">running</span>'

        length = minutes(s.wall_seconds) if s.start and s.end else "—"
        rows.append(
            f"""<li><a href="/s/{quote(s.id)}"{' aria-current="page"' if s is current else ""}>
  <span class="date">{short_date(s.started_at)}</span><span class="title">{escape(clip(first_line(s.headline), 110))}</span>
  <span class="quiet">{len(s.asks)} asks · {length}</span>{end}</a></li>"""
        )
    return f'<ul class="ledger">{"".join(rows)}</ul>'


def _rail_group(
    project: Path, sessions: list[Session], current: Session | None, here: str, at: datetime
) -> str:
    """A project's heading folds its sessions. It starts open while you are reading one of
    them or one was at work in the last week; your own fold, kept in the browser, wins."""
    link = project_href(project)
    on = ' class="on" aria-current="page"' if here == link else ""
    rows = "".join(_rail_row(s, s is current, at) for s in sessions)
    recent = any(s is current for s in sessions) or any(
        _within(s.last_activity, at, RECENT) for s in sessions
    )
    live = (
        '<span class="pulse" title="A session here is still being written"></span>'
        if any(s.is_live(at) for s in sessions)
        else ""
    )
    return f"""<details class="group" data-key="{escape(project_key(project))}" data-open="{int(recent)}"{" open" if recent else ""}>
<summary><h2 class="label" data-n="{len(sessions)}"><a href="{escape(link)}"{on} title="{escape(str(project))}: where it stands">{escape(project.name or str(project))}</a>{live}{icon("chevron")}</h2></summary>
<ul>{rows}</ul></details>"""


def _within(moment: datetime | None, at: datetime, span: timedelta) -> bool:
    return moment is not None and at - moment <= span


def _rail_row(session: Session, is_current: bool, at: datetime) -> str:
    """Title, a dotted leader, then its work time where a page number would be; the day
    it started below. A session with nothing to call it by is set quietly as untitled.
    The one you are reading opens into a card: its day and asks, and when it was worked."""
    untitled = session.headline == session.id
    title = "untitled" if untitled else first_line(session.headline)
    marks = " ".join(name for name, on in (("current", is_current), ("untitled", untitled)) if on)
    attrs = (f' class="{marks}"' if marks else "") + (' aria-current="page"' if is_current else "")
    words = " ".join((title, session.project.name)).lower()
    day = short_date(session.started_at)
    below = (
        f'<span class="date">{day} · {plural(len(session.asks), "ask")}</span>{_rail_strip(session)}'
        if is_current
        else f'<span class="date">{day}</span>'
    )
    return f"""<li data-filter="{escape(words)}"><a href="/s/{quote(session.id)}"{attrs} title="{escape(clip(title, 200))}">
  <span class="title">{escape(clip(title, 90))}</span><span class="leader" aria-hidden="true"></span><span class="figure">{_rail_figure(session, at)}</span>
  {below}</a></li>"""


def _rail_strip(session: Session) -> str:
    """The session at a glance, as a barcode: a mark wherever work happened across its
    active time, red where a check failed."""
    line = Timeline.of(session)
    total = line.active_seconds
    if total <= 0:
        return ""
    marks = "".join(
        f'<i{' class="failed"' if s.failed else ""} style="left:{s.start / total * 100:.2f}%;'
        f'width:{max(s.seconds / total * 100, 0.4):.2f}%"></i>'
        for s in line.segments
        if s.activity != "you"
    )
    return f'<span class="strip" aria-hidden="true">{marks}</span>'


def _rail_figure(session: Session, at: datetime) -> str:
    if session.is_live(at):
        return '<span class="pulse" title="Still being written" aria-label="running"></span><i>writing</i>'
    figure = short_duration(Timeline.of(session).active_seconds)
    if loose := Loose.of(session):
        figure += f'<span class="loose" title="Ended unfinished: {escape(loose.ending)}" aria-label="ended unfinished"></span>'
    return figure
