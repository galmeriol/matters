"""One file's changes as a stack: every edit a layer, the first change at the base and the
latest on top, like a stack of patches. Each layer says which turn made it and what you
had asked there, so a diff never shows up without its reason."""

from html import escape
from pathlib import Path
from urllib.parse import quote

from matters.changes import Change, Stack
from matters.session import Session
from matters.web.frame import layout, rail
from matters.web.icons import icon
from matters.web.library import Library, file_href, href, layer_id, project_href
from matters.web.text import breakable, clip, clock, first_line, short_date
from matters.web.tool_views import diff

OPEN_LAYERS = 6  # layers shown open; the rest fold, to keep the top of the stack in view
LONG_WRITE = 40  # lines: a whole-file write longer than this starts folded


def file_page(
    library: Library, st: Stack, session: Session | None, everywhere: int, oldest_first: bool
) -> str:
    """The stack as a page of its own: what the drawer shows, for links opened without
    the page script, in a new tab, or from the brief."""
    head, stack_list = _parts(library, st, session, everywhere, oldest_first)
    main = f"""<header class="masthead">{head}</header>{stack_list}"""
    return layout(Path(st.path).name, rail(library, "/f", current=session), main)


def file_panel(
    library: Library, st: Stack, session: Session | None, everywhere: int, oldest_first: bool
) -> str:
    """The stack alone, for the drawer the session page opens beside its turns."""
    head, stack_list = _parts(library, st, session, everywhere, oldest_first)
    return f"""<div class="panel-head">{head}<button type="button" class="panel-close" aria-label="Close">✕</button></div>
<div class="panel-body">{stack_list}</div>"""


def _parts(
    library: Library, st: Stack, session: Session | None, everywhere: int, oldest_first: bool
) -> tuple[str, str]:
    project = _project(library, st, session)
    name = st.path.removeprefix(f"{project}/") if project else st.path
    layers = list(st.changes)
    if not oldest_first:
        layers.reverse()
    body = _layers(layers, scoped=session is not None)
    count = len(st.changes)
    failed = (
        f" · {st.failed} failed edit{'s' if st.failed != 1 else ''} not shown" if st.failed else ""
    )
    sessions = len(st.sessions)
    where = "in this session" if session else f"in {sessions} session{'s' if sessions != 1 else ''}"
    scopes = ""
    if session:
        scopes = f"""<nav class="facets" aria-label="Which sessions">
  <a class="facet on" aria-current="true" href="{escape(file_href(st.path, session))}">This session<span class="n">{count}</span></a>
  <a class="facet" href="{escape(file_href(st.path))}">All sessions<span class="n">{everywhere}</span></a></nav>"""
    order = href(
        "/f", path=st.path, s=session.id if session else "", order="" if oldest_first else "oldest"
    )
    kicker_project = (
        f'<a href="{escape(project_href(project))}">{escape(project.name)}</a>'
        if project
        else "File"
    )
    from_session = (
        f'<span><a href="/s/{quote(session.id)}">{escape(clip(first_line(session.headline), 60))}</a></span>'
        if session
        else ""
    )
    head = f"""<p class="kicker">{kicker_project}{from_session}</p>
  <h1 class="path"><code>{breakable(name)}</code></h1>
  <p class="dek">{count} change{"s" if count != 1 else ""} {where} · <span class="plus">+{st.added}</span> <span class="minus">−{st.removed}</span>{failed}</p>
  <p class="resume"><a href="{escape(f"vscode://file{st.path}")}">{icon("file")}Open in VS Code</a>
    <a class="page-only" href="{escape(order)}">{"Latest on top" if oldest_first else "First change on top"}</a>
    <a class="panel-only" href="{escape(file_href(st.path, session))}" target="_blank">Open as a page</a></p>
  <p class="stack-note quiet">Each layer is one edit as the session recorded it, numbered by the turn that made it, latest on top unless reordered; the ask beside it is why.</p>
  {scopes}"""
    return head, f'<ol class="stack">{body}</ol>'


def _layers(layers: list[Change], scoped: bool) -> str:
    """Each layer on the spine carries the number of the turn that made it; more layers
    from the same turn follow it as dots."""
    out: list[str] = []
    seen_turns: set[tuple[str, int]] = set()
    last_session = ""
    previous: tuple[str, int] | None = None
    for shown, change in enumerate(layers):
        if not scoped and change.session.id != last_session:
            last_session = change.session.id
            s = change.session
            out.append(
                f'<li class="stack-session"><a href="/s/{quote(s.id)}">{escape(clip(first_line(s.headline), 90))}</a>'
                f'<span class="quiet">{short_date(s.started_at)}</span></li>'
            )
        key = (change.session.id, change.turn)
        anchor = f' id="{layer_id(change.session, change.turn)}"' if key not in seen_turns else ""
        seen_turns.add(key)
        out.append(_layer(change, anchor, open_=shown < OPEN_LAYERS, same_turn=key == previous))
        previous = key
    return "".join(out)


def _layer(change: Change, anchor: str, open_: bool, same_turn: bool) -> str:
    session, turn = change.session, change.turn
    ask = session.turns[turn - 1].ask
    why = (
        f'<span class="layer-ask" title="{escape(ask.text[:400])}">{escape(clip(first_line(ask.text), 90))}</span>'
        if ask
        else ""
    )
    lines = len(change.hunks[0].new.splitlines()) if change.hunks else 0
    long_write = change.how == "write" and lines > LONG_WRITE
    verb = (
        "Wrote the file"
        if change.how == "write"
        else (change.entry.tool.name if change.entry.tool else "Edit")
    )
    if change.how == "write":
        verb += f" · {lines} lines"
    hunks = (
        "".join(diff(h.old, h.new) for h in change.hunks)
        or '<p class="quiet">No diff recorded for this tool.</p>'
    )
    node = (
        f'<span class="node cont" title="Turn {turn}, continued"></span>'
        if same_turn
        else f'<span class="node" title="Turn {turn}">{turn}</span>'
    )
    moment = " ".join(
        x for x in (short_date(change.entry.at or session.started_at), clock(change.entry.at)) if x
    )
    return f"""<li class="layer"{anchor}>{node}
  <details{" open" if open_ and not long_write else ""}><summary>
    <span class="layer-head"><b>{escape(verb)}</b>
      <a href="/s/{quote(session.id)}#t{turn}" title="Open turn {turn}">{moment}</a>{why}</span>
    <span class="delta"><span class="plus">+{change.added}</span> <span class="minus">−{change.removed}</span></span>
  </summary>{hunks}</details></li>"""


def _project(library: Library, st: Stack, session: Session | None) -> Path | None:
    if session:
        return session.project
    for s in st.sessions:
        if st.path.startswith(f"{s.project}/"):
            return s.project
    return None
