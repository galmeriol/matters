"""One subagent's run, start to finish: what the assistant asked of it, every step it
took, and what it reported back. In the drawer beside the turns, or as a page."""

from datetime import datetime
from html import escape
from urllib.parse import quote

from matters.clock import now
from matters.session import AgentRun, Entry, Session
from matters.web.frame import layout, rail
from matters.web.icons import icon
from matters.web.library import Library, project_href
from matters.web.markdown import render_markdown
from matters.web.text import ago, clip, first_line, plural
from matters.web.tool_views import step_html
from matters.web.work_views import RunView


def agent_page(
    library: Library, session: Session, run: AgentRun, at: datetime | None = None
) -> str:
    """The run as a page of its own: for links opened in a new tab or without the script."""
    head, body = _parts(RunView(session, run, at or now()))
    main = f'<header class="masthead">{head}</header><div class="agent-page">{body}</div>'
    return layout(
        run.description or run.kind, rail(library, f"/s/{session.id}", current=session), main
    )


def agent_panel(
    library: Library, session: Session, run: AgentRun, at: datetime | None = None
) -> str:
    """The run alone, for the drawer the session page opens."""
    head, body = _parts(RunView(session, run, at or now()))
    return f"""<div class="panel-head">{head}<button type="button" class="panel-close" aria-label="Close">✕</button></div>
<div class="panel-body agent-page">{body}</div>"""


def _parts(view: RunView) -> tuple[str, str]:
    session, run = view.session, view.run
    project = session.project
    turn = session.spawned_in().get(run.id)
    back = f"/s/{quote(session.id)}" + (f"#t{turn}" if turn else "")
    where = f"turn {turn}" if turn else "the session"
    facts = " · ".join(escape(f) for f in view.facts)
    head = f"""<p class="kicker"><a href="{escape(project_href(project))}">{escape(project.name or str(project))}</a>
    <span><a href="/s/{quote(session.id)}">{escape(clip(first_line(session.headline), 60))}</a></span></p>
  <p class="agent-head inline">{icon("agent")}<span>Subagent</span><span class="agent-kind">{escape(run.kind)}</span>
    <span class="agent-state {view.state}">{escape(view.word)}</span></p>
  <h1>{escape(clip(view.title, 140))}</h1>
  <p class="dek">{facts}</p>{_running(view)}
  <p class="resume"><a href="{escape(back)}">Back to {where}</a>
    <a class="panel-only" href="{escape(view.href)}" target="_blank">Open as a page</a></p>"""
    sections = []
    if run.prompt:
        sections.append(
            f'<section class="agent-part"><h2 class="label">What it was asked</h2>'
            f'<div class="agent-prompt md">{render_markdown(run.prompt, project)}</div></section>'
        )
    closing = _last_text(run)
    steps = [e for e in run.steps if e is not closing]
    if steps:
        rendered = "".join(step_html(e, project) for e in steps)
        calls = sum(1 for e in steps if e.tool)
        sections.append(
            f'<section class="agent-part"><h2 class="label">What it did <span class="n">{plural(calls, "tool call")}</span></h2>'
            f'<ol class="steps">{rendered}</ol></section>'
        )
    elif not run.entries:
        sections.append(
            "<p class=\"quiet agent-part\">Its transcript isn't on disk, so its steps can't be shown: "
            "only what it was asked and what it reported back.</p>"
        )
    if run.report:
        sections.append(
            f'<section class="agent-part"><h2 class="label">What it reported</h2>'
            f'<div class="agent-report-full md">{render_markdown(run.report, project)}</div></section>'
        )
    elif view.is_running:
        sections.append(
            '<p class="quiet agent-part">Still at work: what it reports comes back when it '
            "finishes. Refresh to see the steps it has taken since.</p>"
        )
    elif not run.finished:
        sections.append(
            '<p class="quiet agent-part">No report was recorded: its journal went quiet before '
            "it finished, so it was stopped or the session ended first.</p>"
        )
    return head, "".join(sections)


def _running(view: RunView) -> str:
    """A run still at work: when it last moved, and the way to load what came since."""
    if not view.is_running or not (latest := view.run.last_at):
        return ""
    quiet = (view.at - latest).total_seconds()
    return (
        f'<p class="ended live"><b>Running</b><span class="pulse" aria-hidden="true"></span>'
        f'Last step <time class="ago" datetime="{latest.isoformat()}">{ago(quiet)}</time>'
        f' <a class="refresh" href="{escape(view.href)}" data-refresh>{icon("refresh")}Refresh</a></p>'
    )


def _last_text(run: AgentRun) -> Entry | None:
    """Its closing words, shown as the report rather than twice."""
    if not run.report:
        return None
    return next((e for e in reversed(run.steps) if e.kind == "text"), None)
