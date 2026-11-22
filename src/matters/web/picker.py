"""Picking sessions for a model to read (to extract knowledge): grouped by project, a project's box ticks all its sessions, and a live
estimate of tokens at the bottom (viewer.js reads the form's data-*). No cost: it runs on the user's own Claude Code plan."""

from collections import defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

from matters.llm import Provider
from matters.session import Session
from matters.transcript import Transcript, budget
from matters.web.frame import layout, rail
from matters.web.library import Library, by_recency
from matters.web.text import clip, first_line, short_date


@dataclass(frozen=True, slots=True)
class Pick:
    """What the picker is for."""

    title: str  # "Extract preferences and facts"
    kicker: str  # "Knowledge"
    dek: str  # what will happen, one or two sentences
    action: str  # where the form posts
    button: str  # "Extract from selected"
    here: str  # this page's path, for the rail
    done: frozenset[str] = frozenset()  # sessions already done
    done_label: str = ""  # "read"


def picker_page(library: Library, selected: set[str], provider: Provider | None, pick: Pick) -> str:
    ready = provider is not None and provider.configured()
    model = provider.model if provider else ""
    shown = library.sessions
    by_project: dict[Path, list[Session]] = defaultdict(list)
    for session in by_recency(shown):
        by_project[session.project].append(session)
    groups = "".join(_pick_group(p, group, selected, pick) for p, group in by_project.items())
    disabled = "" if ready else " disabled"
    primary = ' class="primary"' if ready else ""
    runs_on = "headless Claude Code" if provider else "off"
    main = f"""
<header class="masthead"><p class="kicker">{escape(pick.kicker)}<span>{runs_on}</span>{f"<span>{escape(model)}</span>" if model else ""}</p>
  <h1>{escape(pick.title)}</h1>
  <p class="dek">{pick.dek}</p></header>
{"" if ready else no_key(provider)}
<form class="pick" method="post" action="{escape(pick.action)}" data-budget="{budget()}">
  {groups or '<p class="quiet">No sessions.</p>'}
  <div class="pick-bar"><span class="estimate" aria-live="polite">Nothing selected</span><button type="submit"{primary}{disabled}>{escape(pick.button)}</button></div>
</form>"""
    return layout(pick.title, rail(library, pick.here), main)


def no_key(provider: Provider | None) -> str:
    if provider is None:
        return '<div class="notice"><p><b>Model features are off in this viewer.</b></p></div>'
    return f"""<div class="notice"><p><b>Extraction runs on Claude Code, which isn't installed here.</b>
{provider.setup_hint}, then restart matters (<code>matters stop</code>, <code>matters start</code>).</p></div>"""


def _pick_group(project: Path, sessions: list[Session], selected: set[str], pick: Pick) -> str:
    rows = "".join(
        f"""<li><label><input type="checkbox" name="s" value="{escape(s.id)}" data-chars="{Transcript.size_of(s)}"{" checked" if s.id in selected else ""}>
  <span class="date">{short_date(s.started_at)}</span><span class="title">{escape(clip(first_line(s.headline), 110))}</span>
  <span class="quiet">{len(s.asks)} asks{f" · {escape(pick.done_label)}" if s.id in pick.done else ""}</span></label></li>"""
        for s in sessions
    )
    return f"""<fieldset class="pick-group"><legend><label><input type="checkbox" class="all">
  <span>{escape(project.name or str(project))}</span></label></legend><ul>{rows}</ul></fieldset>"""
