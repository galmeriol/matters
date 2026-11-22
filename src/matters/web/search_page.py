"""Search results: hits grouped by session, each a turn you can open with the words marked."""

from html import escape
from urllib.parse import quote

from matters.search import WHERE_LABELS, WHERES, Hit, Results, Where, excerpt
from matters.session import Session
from matters.web.frame import layout, rail
from matters.web.library import Library, href, project_href
from matters.web.text import clip, first_line, short_date

PER_SESSION = 5


def search_page(library: Library, query: str, results: Results, where: Where | None) -> str:
    total = sum(results.counts.values())
    sessions = results.by_session()
    facets = _facet("All", total, query, None, where is None) + "".join(
        _facet(WHERE_LABELS[w], results.counts[w], query, w, where == w) for w in WHERES
    )
    blocks = "".join(_session(library, s, hits, query, results.terms) for s, hits in sessions)
    if not results.terms:
        empty = "Type words to search for; put a phrase in quotes."
    elif not results.hits:
        empty = "Nothing matches. Every word has to appear in the same ask, answer or step."
    else:
        empty = ""
    scope = f" in {WHERE_LABELS[where].lower()}" if where else ""
    dek = (
        f"{len(results.hits)} hit{'s' if len(results.hits) != 1 else ''}{scope} "
        f"in {len(sessions)} of {len(library.sessions)} sessions"
    )
    main = f"""
<header class="masthead"><p class="kicker">Search</p>
  <h1>“{escape(query)}”</h1><p class="dek">{dek}</p>
  <nav class="facets" aria-label="Search in">{facets}</nav></header>
<div class="hits">{blocks or f'<p class="quiet">{empty}</p>'}</div>"""
    return layout(f"Search: {query}", rail(library, "/search", query=query), main)


def _facet(label: str, count: int, query: str, where: Where | None, on: bool) -> str:
    link = href("/search", q=query, **({"in": where} if where else {}))
    current = ' aria-current="true"' if on else ""
    return f'<a class="facet{" on" if on else ""}" href="{escape(link)}"{current}>{label}<span class="n">{count}</span></a>'


def _session(
    library: Library, first: Session, hits: list[Hit], query: str, terms: tuple[str, ...]
) -> str:
    shown = "".join(_hit(h, query, terms) for h in hits[:PER_SESSION])
    more = len(hits) - PER_SESSION
    rest = (
        f'<p class="more"><a href="{escape(_open(first.id, query, hits[PER_SESSION].turn))}">'
        f"{more} more in this session →</a></p>"
        if more > 0
        else ""
    )
    return f"""<section class="hit-group">
  <h2><a href="/s/{quote(first.id)}">{escape(clip(first_line(first.headline), 110))}</a></h2>
  <p class="quiet"><a href="{escape(project_href(first.project))}">{escape(first.project.name)}</a> · {short_date(first.started_at)} · {len(hits)} hit{"s" if len(hits) != 1 else ""}</p>
  <ol>{shown}</ol>{rest}</section>"""


def _hit(hit: Hit, query: str, terms: tuple[str, ...]) -> str:
    runs = "".join(
        f"<mark>{escape(piece)}</mark>" if marked else escape(piece)
        for piece, marked in excerpt(hit.text, terms)
    )
    return f"""<li class="hit in-{hit.where}"><a href="{escape(_open(hit.session.id, query, hit.turn))}">
  <span class="where"><span class="t">{hit.turn}</span><span class="what" title="{escape(hit.label)}">{escape(hit.label)}</span></span><span class="excerpt">{runs}</span></a></li>"""


def _open(session_id: str, query: str, turn: int) -> str:
    return href(f"/s/{quote(session_id)}", hl=query) + f"#t{turn}"
