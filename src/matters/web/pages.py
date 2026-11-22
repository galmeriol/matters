"""The small pages: nothing yet, nothing here, and a background job at work."""

from html import escape

from matters.jobs import Job
from matters.web.frame import layout, rail
from matters.web.icons import mark
from matters.web.library import Library
from matters.web.text import clip, first_line


def empty_page(library: Library) -> str:
    main = """<header class="masthead"><p class="kicker">matters</p><h1>No sessions yet</h1>
<p class="dek">Claude Code sessions appear here as soon as they exist in ~/.claude/projects.</p></header>"""
    return layout("matters", rail(library, "/"), main)


def not_found_page(library: Library) -> str:
    main = '<header class="masthead"><p class="kicker">404</p><h1>Nothing here</h1></header>'
    return layout("Not found", rail(library, "/"), main)


def job_page(library: Library, job: Job) -> str:
    known = {s.id: s for s in library.sessions}
    names = "".join(
        f"<li>{escape(clip(first_line(known[sid].headline), 90)) if sid in known else escape(sid)}</li>"
        for sid in job.session_ids
    )
    if job.state == "failed":
        retry = _retry_form(*job.retry) if job.retry else ""
        body = f"""<div class="notice err"><p><b>{escape(job.title)} failed.</b> {escape(job.error)}</p></div>
{retry}"""
        refresh = ""
    else:
        body = f"""<div class="working" data-job-state="running" data-elapsed="{job.elapsed}">{mark("drawing")}
  <p role="status"><b>{escape(job.title)}</b> · <span class="elapsed">{job.elapsed} s</span> · {escape(job.detail)}<br>
  <span class="quiet">Usually one to a few minutes. This page moves on by itself when it's done.</span></p></div>"""
        refresh = '<noscript><meta http-equiv="refresh" content="3"></noscript>'
    heading = f"{job.title} failed" if job.state == "failed" else f"{job.title}…"
    main = f"""{refresh}
<header class="masthead"><p class="kicker">Background job<span>{job.id}</span></p>
  <h1>{escape(heading)}</h1></header>
<div class="prose">{body}<h2 class="label">Sessions</h2><ul>{names}</ul></div>"""
    return layout(job.title, rail(library, "/jobs"), main)


def _retry_form(path: str, form: dict[str, list[str]]) -> str:
    hidden = "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">'
        for k, vs in form.items()
        for v in vs
    )
    return f'<form method="post" action="{escape(path)}" class="retry">{hidden}<button type="submit">Try again</button></form>'
