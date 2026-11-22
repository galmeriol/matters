"""A project's brief: where you left off, what is still open, what you settled (accepted
knowledge), which files changed and in which turns, and every session. The page to open
first when you come back to a project."""

import shlex
from html import escape
from urllib.parse import quote

from matters.brief import ENDING_LABELS, Brief, Touch
from matters.knowledge.model import GLOBAL
from matters.web.frame import layout, rail, sessions_list
from matters.web.human import ask_html
from matters.web.icons import icon
from matters.web.library import Library, file_href, href, knowledge_href, project_href
from matters.web.markdown import render_markdown
from matters.web.text import breakable, clip, first_line, short_date, when

FILES_SHOWN = 25


def brief_page(library: Library, b: Brief) -> str:
    latest = b.latest
    first = b.sessions[-1].started_at if b.sessions else None
    span = f"{short_date(first)} – {short_date(latest.ended_at if latest else None)}"
    count = len(b.sessions)
    resume = f"cd {shlex.quote(str(b.project))} && claude --resume {latest.id}" if latest else ""
    resume_row = (
        f"""<p class="resume"><code>{escape(resume)}</code>
    <button type="button" data-copy="{escape(resume)}">Copy</button>
    <a href="/p/{quote(b.project.name or str(b.project), safe="")}.md">{icon("download")}Brief as Markdown</a></p>"""
        if latest
        else ""
    )
    main = f"""
<header class="masthead"><p class="kicker">Project<span title="{escape(str(b.project))}">{escape(str(b.project))}</span></p>
  <h1>{escape(b.project.name or str(b.project))}</h1>
  <p class="dek">{count} session{"s" if count != 1 else ""} · {span} · {len(b.files)} files edited</p>
  {resume_row}
</header>
<div class="brief">
  {_left_off(b)}
  {_loose(b)}
  {_knowledge(library, b)}
  {_files(b)}
  <section class="brief-part"><h2 class="label">Sessions</h2>{sessions_list(b.sessions)}</section>
</div>"""
    return layout(b.project.name or str(b.project), rail(library, project_href(b.project)), main)


def _left_off(b: Brief) -> str:
    if not b.latest or not (turn := b.last):
        return ""
    n = turn.number
    session = b.latest
    answer = (
        f'<div class="answer clipped"><div class="md">{render_markdown(turn.answer.text, session.project)}</div></div>'
        if turn.answer
        else '<p class="quiet">No answer was recorded for this ask.</p>'
    )
    return f"""<section class="brief-part left-off"><h2 class="label">Where you left off</h2>
  <p class="where-from"><a href="/s/{quote(session.id)}#t{n}">{escape(clip(first_line(session.headline), 100))} · turn {n}</a>
    <span class="quiet">{when(turn.ask.at if turn.ask else session.ended_at)}</span></p>
  {ask_html(turn.ask) if turn.ask else ""}
  {answer}
  <p class="more"><a href="/s/{quote(session.id)}#t{n}">Read the whole turn →</a></p>
</section>"""


def _loose(b: Brief) -> str:
    if not b.loose:
        return ""
    rows = "".join(
        f"""<li><span class="badge {x.ending}">{ENDING_LABELS[x.ending]}</span>
  <a href="/s/{quote(x.session.id)}#t{x.turn}">{escape(clip(x.text, 220))}</a>
  <span class="quiet">{escape(clip(first_line(x.session.headline), 60))} · {short_date(x.session.ended_at or x.session.started_at)}</span></li>"""
        for x in b.loose
    )
    return f"""<section class="brief-part"><h2 class="label">Still open <span class="quiet">· how sessions ended unfinished</span></h2>
  <ul class="loose-list">{rows}</ul></section>"""


def _knowledge(library: Library, b: Brief) -> str:
    here = str(b.project)
    mine = [i for i in library.knowledge if i.scope == here and i.status == "accepted"]
    waiting = sum(1 for i in library.knowledge if i.scope == here and i.status == "candidate")
    everywhere = sum(1 for i in library.knowledge if i.scope == GLOBAL and i.status == "accepted")
    if not (mine or waiting):
        return ""
    rows = "".join(
        f'<li><a href="{escape(knowledge_href(i))}"><span class="state">{escape(i.kind)}</span>{escape(i.statement)}</a></li>'
        for i in mine
    )
    notes = [] if mine else ["Nothing accepted for this project yet"]
    if waiting:
        more = "more " if mine else ""
        notes.append(
            f'<a href="{escape(href("/knowledge", scope=here))}">{waiting} {more}waiting for review</a>'
        )
    if everywhere:
        notes.append(f"{everywhere} global items also apply")
    tail = f'<p class="quiet">{" · ".join(notes)}</p>' if notes else ""
    return f"""<section class="brief-part"><h2 class="label">Settled <span class="quiet">· accepted knowledge for this project</span></h2>
  <ul class="settled">{rows}</ul>{tail}</section>"""


def _files(b: Brief) -> str:
    if not b.files:
        return ""
    rows = "".join(
        f"""<tr><td><a class="file" href="{escape(file_href(f.absolute))}" title="{escape(f.absolute)}: every change, stacked"><code>{breakable(f.path)}</code></a></td>
  <td class="num">{f.edits}</td>
  <td>{"".join(f'<a href="/s/{quote(t.session.id)}#t{t.turn}" title="{escape(clip(first_line(t.session.headline), 80))}, turn {t.turn}">{short_date(t.session.started_at)} · t{t.turn}</a>' for t in _distinct(f.touches)[:4])}</td></tr>"""
        for f in b.files[:FILES_SHOWN]
    )
    more = len(b.files) - FILES_SHOWN
    extra = [
        f"{more} more files" if more > 0 else "",
        f"{b.outside} outside the project" if b.outside else "",
    ]
    said = " · ".join(e for e in extra if e)
    tail = f'<p class="quiet">And {said}.</p>' if said else ""
    return f"""<section class="brief-part"><h2 class="label">Files touched <span class="quiet">· most recent first, with the turns that changed them</span></h2>
  <table class="file-table"><thead><tr><th>File</th><th class="num">Edits</th><th>Turns</th></tr></thead><tbody>{rows}</tbody></table>{tail}</section>"""


def _distinct(touches: tuple[Touch, ...]) -> list[Touch]:
    """One link per turn, however many edits it made."""
    seen: set[tuple[str, int]] = set()
    out = []
    for t in touches:
        if (t.session.id, t.turn) not in seen:
            seen.add((t.session.id, t.turn))
            out.append(t)
    return out
