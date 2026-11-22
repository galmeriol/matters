"""Pages for knowledge: review what extraction proposed, keep what you accepted, and
export it as PREFERENCES.md and FACTS.md.

Review is one form: tick rows (or a whole group) and accept or reject them together,
or decide one row with its own buttons. Statements are editable in place and the
edit is what gets kept; scope can be switched between global and the project.
"""

from dataclasses import dataclass, field
from html import escape
from urllib.parse import quote

from matters.knowledge.export import FILES, markdown
from matters.knowledge.model import CATEGORIES, GLOBAL, KINDS, Item, Kind, scope_name
from matters.llm import Provider
from matters.session import Session
from matters.web.frame import layout, rail
from matters.web.icons import icon
from matters.web.library import Library, href, knowledge_href
from matters.web.picker import Pick, no_key, picker_page
from matters.web.text import clip, first_line, plural

VIEWS = {
    "review": ("Review", "candidate"),
    "accepted": ("Accepted", "accepted"),
    "rejected": ("Rejected", "rejected"),
}
KIND_TITLES: dict[Kind, str] = {"preference": "Preferences", "fact": "Facts"}


def pick_page(
    library: Library, selected: set[str], provider: Provider | None, read: frozenset[str]
) -> str:
    pick = Pick(
        title="Extract preferences and facts",
        kicker="Knowledge",
        dek="Pick the sessions to read. A model proposes the preferences and facts they show, "
        "mostly from how you reacted: what you stated, corrected, chose and rejected. "
        "Nothing is kept until you accept it.",
        action="/knowledge/extract",
        button="Extract from selected",
        here="/knowledge",
        done=read,
        done_label="read",
    )
    return picker_page(library, selected, provider, pick)


@dataclass(frozen=True)
class Fresh:
    """What the last extraction brought, by item id: marked on its rows while you review
    them. `announce` right after it finished, to say what it found."""

    new: frozenset[int] = field(default_factory=frozenset)
    merged: frozenset[int] = field(default_factory=frozenset)  # known items, more evidence
    announce: bool = False

    @staticmethod
    def ids(text: str) -> frozenset[int]:
        """'12,13' -> {12, 13}; anything that isn't a number is ignored."""
        return frozenset(int(n) for n in text.split(",") if n.isdigit())

    @classmethod
    def of(cls, new: str, merged: str, announce: bool = False) -> "Fresh":
        return cls(cls.ids(new), cls.ids(merged), announce)

    def to_params(self) -> dict[str, str]:
        """The marks, to carry across a decision (not the announcement)."""
        return {
            "new": ",".join(map(str, sorted(self.new))),
            "merged": ",".join(map(str, sorted(self.merged))),
        }

    def mark(self, item: Item) -> str:
        """'New', 'More evidence', or nothing."""
        return "New" if item.id in self.new else "More evidence" if item.id in self.merged else ""

    def notice(self, items: list[Item]) -> str:
        """What the extraction found: how many new, where they are, what grew."""
        if not self.announce:
            return ""
        known = {i.id: i for i in items}
        new = [known[i] for i in sorted(self.new) if i in known]
        found = (
            f'<b>{len(new)} new to review</b>, marked <span class="kn-fresh">New</span>, first in their groups. '
            f'<a href="#k{new[0].id}">Go to the first</a>'
            if new
            else "<b>Nothing new to review.</b>"
        )
        grown = [known[i] for i in sorted(self.merged) if i in known]
        repeats = (
            f" · {plural(len(grown), 'repeat')} added evidence to "
            f'<a href="{escape(knowledge_href(grown[0]))}">{"a known item" if len(grown) == 1 else "known items"}</a>'
            if grown
            else ""
        )
        return f'<div class="notice"><p>{found}{repeats}.</p></div>'


def knowledge_page(
    library: Library,
    items: list[Item],
    view: str,
    scope: str,
    provider: Provider | None,
    fresh: Fresh | None = None,
) -> str:
    fresh = fresh or Fresh()
    view = view if view in VIEWS else "review"
    status = VIEWS[view][1]
    counts = {v: sum(1 for i in items if i.status == s) for v, (_, s) in VIEWS.items()}
    tabs = "".join(
        f'<a class="kn-tab{" on" if v == view else ""}" href="{escape(href("/knowledge", view="" if v == "review" else v, scope=scope))}"'
        f'{' aria-current="page"' if v == view else ""}>{label}<span class="n">{counts[v]}</span></a>'
        for v, (label, _) in VIEWS.items()
    )
    shown = [i for i in items if i.status == status]
    scopes = sorted({i.scope for i in shown}, key=lambda s: (s != GLOBAL, scope_name(s)))
    chips = "".join(
        f'<a class="facet{" on" if s == scope else ""}" href="{escape(href("/knowledge", view="" if view == "review" else view, scope="" if s == scope else s))}">'
        f'{escape(scope_name(s))}<span class="n">{sum(1 for i in shown if i.scope == s)}</span></a>'
        for s in scopes
    )
    shown = [i for i in shown if not scope or i.scope == scope]
    flash = fresh.notice(items)
    ready = provider is not None and provider.configured()
    main = f"""
<header class="masthead"><p class="kicker">Preferences &amp; facts</p><h1>Knowledge</h1>
  <p class="dek">What your sessions say about how you work and what is true, kept only once you accept it.</p>
  <p class="kn-actions"><a class="button" href="/knowledge/pick">{icon("bulb")}Extract from sessions</a>
    <a class="button" href="/knowledge/export">{icon("download")}Export PREFERENCES.md &amp; FACTS.md</a></p></header>
{flash}{"" if ready or items else no_key(provider)}
<nav class="kn-tabs" aria-label="Knowledge">{tabs}</nav>
{f'<div class="facets kn-scopes" aria-label="Scope">{chips}</div>' if len(scopes) > 1 or scope else ""}
{_list(library, shown, items, view, scope, fresh) if shown else _empty(view)}"""
    return layout("Knowledge", rail(library, "/knowledge"), main)


def _empty(view: str) -> str:
    text = {
        "review": 'Nothing to review. <a href="/knowledge/pick">Extract from some sessions</a>: what they propose waits here.',
        "accepted": "Nothing accepted yet. Accepted items are what the export contains.",
        "rejected": "Nothing rejected. Rejected items are never proposed again.",
    }[view]
    return f'<p class="kn-empty quiet">{text}</p>'


def _list(
    library: Library,
    shown: list[Item],
    everything: list[Item],
    view: str,
    scope: str,
    fresh: Fresh,
) -> str:
    sessions = {s.id: s for s in library.sessions}
    by_id = {i.id: i for i in everything}
    groups = []
    for kind in KINDS:
        for category in (*CATEGORIES, *sorted({i.category for i in shown} - set(CATEGORIES))):
            group = [i for i in shown if i.kind == kind and i.category == category]
            if not group:
                continue
            group.sort(key=lambda i: i.id not in fresh.new)  # the new ones first
            rows = "".join(_row(i, sessions, by_id, view, fresh.mark(i)) for i in group)
            groups.append(
                f"""<fieldset class="kn-group"><legend><label><input type="checkbox" class="all">
  <span>{KIND_TITLES[kind]} <span class="quiet">· {escape(category)}</span></span></label></legend><ul>{rows}</ul></fieldset>"""
            )
    buttons = {
        "review": '<button type="submit" name="action" value="accept" class="primary" data-needs-selection data-busy="Accepting…">Accept selected</button>'
        '<button type="submit" name="action" value="reject" data-needs-selection data-busy="Rejecting…">Reject selected</button>',
        "accepted": '<button type="submit" name="action" value="save" class="primary" data-busy="Saving…">Save edits</button>'
        '<button type="submit" name="action" value="reject" data-needs-selection data-busy="Rejecting…">Reject selected</button>',
        "rejected": '<button type="submit" name="action" value="restore" class="primary" data-needs-selection data-busy="Restoring…">Back to review</button>',
    }[view]
    return f"""<form class="kn" method="post" action="/knowledge/decide">
  <input type="hidden" name="view" value="{escape(view)}"><input type="hidden" name="scope" value="{escape(scope)}">
  {"".join(f'<input type="hidden" name="{k}" value="{v}">' for k, v in fresh.to_params().items() if v)}
  {"".join(groups)}
  <div class="pick-bar kn-bar"><span class="kn-count" aria-live="polite">{len(shown)} item{"s" if len(shown) != 1 else ""}</span>{buttons}</div>
</form>"""


def _row(
    item: Item, sessions: dict[str, Session], by_id: dict[int, Item], view: str, mark: str = ""
) -> str:
    projects = {
        str(sessions[e.session_id].project) for e in item.evidence if e.session_id in sessions
    }
    options = [GLOBAL, *sorted(projects | ({item.scope} - {GLOBAL}))]
    select = "".join(
        f'<option value="{escape(o)}"{" selected" if o == item.scope else ""}>{escape(scope_name(o))}</option>'
        for o in options
    )
    basis = "stated" if item.basis == "stated" else "from a reaction"
    seen = f" · seen in {item.sessions} sessions" if item.sessions > 1 else ""
    related = by_id.get(item.related_id) if item.related_id else None
    relation = (
        f'<p class="kn-relation"><b>{"Replaces" if item.relation == "updates" else "Contradicts"}:</b> {escape(related.statement)}</p>'
        if related and item.relation in ("updates", "contradicts") and view == "review"
        else ""
    )
    why = (
        f'<p class="kn-why"><span class="quiet">Why:</span> {escape(item.why)}</p>'
        if item.why
        else ""
    )
    quick = (
        f"""<div class="kn-quick"><button type="submit" name="one" value="accept:{item.id}" title="Accept" aria-label="Accept">✓</button>
  <button type="submit" name="one" value="reject:{item.id}" title="Reject" aria-label="Reject">✕</button></div>"""
        if view == "review"
        else ""
    )
    badge = f'<span class="kn-fresh">{mark}</span>' if mark else ""
    return f"""<li class="kn-row{" fresh" if mark else ""}" id="k{item.id}">
  <input type="checkbox" name="id" value="{item.id}" aria-label="Select">
  <div class="kn-main">
    <textarea class="kn-text" name="text-{item.id}" rows="1" aria-label="Statement">{escape(item.statement)}</textarea>
    <p class="kn-meta"><select name="scope-{item.id}" aria-label="Scope">{select}</select>
      {badge}<span class="kn-basis {item.basis}">{basis}</span><span class="quiet">{seen}</span></p>
    {relation}{why}
    {_evidence(item, sessions)}
  </div>
  {quick}
</li>"""


def _evidence(item: Item, sessions: dict[str, Session]) -> str:
    """Your own words, always in sight: the first quote shows, the rest fold."""
    if not item.evidence:
        return ""
    first, *rest = item.evidence
    shown = (
        f'<ul class="kn-evidence">{_cite(first.session_id, first.turn, first.quote, sessions)}</ul>'
    )
    if not rest:
        return shown
    more = "".join(_cite(e.session_id, e.turn, e.quote, sessions) for e in rest)
    return (
        f'{shown}<details class="kn-more"><summary>{len(rest)} more</summary>'
        f'<ul class="kn-evidence">{more}</ul></details>'
    )


def _cite(session_id: str, turn: int, quote_text: str, sessions: dict[str, Session]) -> str:
    session = sessions.get(session_id)
    where = (
        f'<a href="/s/{quote(session_id)}#t{turn}">{escape(session.project.name)} · {escape(clip(first_line(session.headline), 50))} · turn {turn}</a>'
        if session
        else f'<span class="quiet">a session no longer here · turn {turn}</span>'
    )
    return f"<li><q>{escape(quote_text)}</q> {where}</li>"


def export_page(library: Library, items: list[Item], scope: str, date: str) -> str:
    accepted = [i for i in items if i.status == "accepted"]
    scopes = sorted(
        {i.scope for i in accepted} | {GLOBAL}, key=lambda s: (s != GLOBAL, scope_name(s))
    )
    scope = scope if scope in scopes else GLOBAL
    chips = "".join(
        f'<a class="facet{" on" if s == scope else ""}" href="{escape(href("/knowledge/export", scope=s))}">'
        f'{escape(scope_name(s))}<span class="n">{sum(1 for i in accepted if i.scope == s)}</span></a>'
        for s in scopes
    )
    panels = "".join(_panel(accepted, kind, scope, date) for kind in KINDS)
    where = "~/.claude/" if scope == GLOBAL else f"{escape(scope)}/"
    main = f"""
<header class="masthead"><p class="kicker">Knowledge · export</p><h1>PREFERENCES.md &amp; FACTS.md</h1>
  <p class="dek">Only accepted items, for one scope at a time. Nothing on disk changes until you save a file.</p></header>
<div class="facets kn-scopes kn-export-scopes" aria-label="Scope">{chips}</div>
<p class="kn-hint quiet">To have every Claude Code session read them, save both files in <code>{where}</code> next to
<code>CLAUDE.md</code> and add these two lines to it: <code>@PREFERENCES.md</code> and <code>@FACTS.md</code>.</p>
<div class="kn-export">{panels}</div>"""
    return layout("Export knowledge", rail(library, "/knowledge"), main)


def _panel(items: list[Item], kind: Kind, scope: str, date: str) -> str:
    text = markdown(items, kind, scope, date)
    count = sum(1 for i in items if i.kind == kind and i.scope == scope)
    name = FILES[kind]
    return f"""<section class="kn-file"><header><h2>{name} <span class="quiet">{count} item{"s" if count != 1 else ""}</span></h2>
  <button type="button" data-copy="{escape(text)}">Copy</button>
  <a class="button" href="{escape(href(f"/knowledge/export/{name}", scope=scope))}" download="{name}">{icon("download")}Download</a></header>
<pre>{escape(text)}</pre></section>"""
