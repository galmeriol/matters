import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from http.cookies import CookieError, SimpleCookie
from importlib.resources import files
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, quote, unquote, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server
from wsgiref.types import StartResponse, WSGIEnvironment

from matters.brief import Brief
from matters.changes import Stack
from matters.knowledge.export import FILES, markdown
from matters.knowledge.model import GLOBAL
from matters.knowledge.store import ACTIONS, KnowledgeStore
from matters.search import WHERES, Results
from matters.session import Session
from matters.sources import Source
from matters.web.agent_page import agent_page, agent_panel
from matters.web.brief_page import brief_page
from matters.web.file_page import file_page, file_panel
from matters.web.knowledge_pages import Fresh, export_page, knowledge_page, pick_page
from matters.web.library import Library, href
from matters.web.orders import ORDERS, TurnOrders
from matters.web.pages import empty_page, job_page, not_found_page
from matters.web.search_page import search_page
from matters.web.session_page import session_page
from matters.web.timeline_view import timeline_view
from matters.workbench import Workbench

# Pages are self-contained: inline style and script, images only as data: URIs, and the
# one bundled script (Mermaid) served from here. Forms may only post back to this
# server; scripts may only fetch from it (job polling).
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
    "img-src data:; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
HTML = "text/html; charset=utf-8"
MERMAID = "mermaid-11.4.1.min.js"  # versioned name: it can be cached for good
VENDORED = frozenset({MERMAID})


@cache
def _vendored(name: str) -> str:
    """A bundled script, read once (Mermaid is 2.6 MB)."""
    return files("matters.web").joinpath("vendor", name).read_text(encoding="utf-8")


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
MAX_FORM = 1_000_000


@dataclass(frozen=True, slots=True)
class Response:
    status: str
    body: str = ""
    headers: list[tuple[str, str]] = field(default_factory=list)
    content_type: str = HTML

    @classmethod
    def page(cls, html: str) -> "Response":
        return cls("200 OK", html)

    @classmethod
    def markdown(cls, text: str, download: str = "") -> "Response":
        """Markdown as text; with a file name, as a file to save."""
        headers = (
            [("Content-Disposition", f'attachment; filename="{download}"')] if download else []
        )
        return cls("200 OK", text, headers, "text/markdown; charset=utf-8")

    @classmethod
    def redirect(cls, location: str, status: str = "303 See Other") -> "Response":
        return cls(status, headers=[("Location", location)])

    @classmethod
    def forbidden(cls) -> "Response":
        return cls("403 Forbidden", "Requests must come from this viewer.", [], "text/plain")

    def with_cookie(self, value: str) -> "Response":
        """The same response, asking the browser to keep a choice (a Set-Cookie value)."""
        return Response(
            self.status, self.body, [*self.headers, ("Set-Cookie", value)], self.content_type
        )


@dataclass(frozen=True, slots=True)
class Request:
    """What a request asks for: the path in parts, the query, a posted form, and the
    choices your browser keeps for this viewer (cookies)."""

    parts: list[str]
    params: dict[str, list[str]]
    method: str = "GET"
    form: dict[str, list[str]] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        path: str,
        query: str,
        method: str = "GET",
        form: dict[str, list[str]] | None = None,
        cookie: str = "",
    ) -> "Request":
        parts = path.strip("/").split("/")
        return cls(parts, parse_qs(query), method, form or {}, _cookies(cookie))

    def param(self, name: str) -> str:
        return self.params.get(name, [""])[0]

    @property
    def query(self) -> str:
        return self.param("q").strip()


class Viewer:
    """WSGI app. Every request re-asks the sources, which only re-read changed files,
    so reloading a page shows a session that is still being written.

    `bench` does what needs a model (extracting knowledge). Without one that feature
    is off; without credentials the pages say how to add them.
    """

    def __init__(self, sources: Sequence[Source], bench: Workbench | None = None) -> None:
        self.sources = sources
        self.bench = bench
        self._lock = threading.Lock()  # the sources' caches aren't thread-safe

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        if not _trusted(environ):
            response = Response.forbidden()
        else:
            form = _form(environ) if method == "POST" else {}
            response = self.route(
                environ.get("PATH_INFO", "/"),
                environ.get("QUERY_STRING", ""),
                method,
                form,
                environ.get("HTTP_COOKIE", ""),
            )
        body = response.body.encode("utf-8")
        start_response(
            response.status,
            [
                ("Content-Type", response.content_type),
                ("Content-Length", str(len(body))),
                ("Content-Security-Policy", CSP),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "same-origin"),
                *response.headers,
            ],
        )
        return [body]

    def route(
        self,
        path: str,
        query_string: str,
        method: str = "GET",
        form: dict[str, list[str]] | None = None,
        cookie: str = "",
    ) -> Response:
        library = self.library()
        request = Request.of(path, query_string, method, form, cookie)
        return self.answer(library, request) or Response("404 Not Found", not_found_page(library))

    def answer(self, library: Library, request: Request) -> Response | None:
        """What the request is for, or None when there is nothing at its path."""
        match request.parts:
            case [""] if request.query:
                return self.search(library, request)
            case [""]:
                if latest := _most_recent(library.sessions):
                    return Response.redirect(f"/s/{quote(latest.id)}", "302 Found")
                return Response.page(empty_page(library))
            case ["search"]:
                return self.search(library, request)
            case ["s", session_id]:
                if session := library.session(session_id):
                    return self.session(library, session, request)
            case ["s", session_id, "agents", agent_id]:
                session = library.session(session_id)
                if session and (run := session.agent(agent_id)):
                    render = agent_panel if request.param("panel") == "1" else agent_page
                    return Response.page(render(library, session, run))
            case ["p", name] if name.endswith(".md"):
                if project := library.project_named(unquote(name.removesuffix(".md"))):
                    return Response.markdown(Brief.of(library.sessions, project).to_markdown())
            case ["p", name]:
                if project := library.project_named(unquote(name)):
                    return Response.page(brief_page(library, Brief.of(library.sessions, project)))
            case ["f"]:
                return self.file(library, request)
            case ["knowledge", *rest] if bench := self.bench:
                return self.knowledge(bench, library, rest, request)
            case ["static", name] if name in VENDORED:
                return Response(
                    "200 OK",
                    _vendored(name),
                    [("Cache-Control", "max-age=31536000, immutable")],
                    "text/javascript; charset=utf-8",
                )
            case ["jobs", number] if number.isdigit() and self.bench:
                job = self.bench.jobs.get(int(number))
                if job and job.state == "done" and job.result_url:
                    return Response.redirect(job.result_url)
                if job:
                    return Response.page(job_page(library, job))
        return None

    def session(self, library: Library, session: Session, request: Request) -> Response:
        """A session's page, its turns in its own order or else the default. Picking one
        (?order=) keeps it for this session alone, then comes back to the page."""
        orders = TurnOrders.from_cookies(request.cookies)
        if (order := request.param("order")) in (value for value, _ in ORDERS):
            picked = orders.picking(session.id, order)
            back = Response.redirect(f"/s/{quote(session.id)}")
            return back if picked == orders else back.with_cookie(picked.to_cookie())
        newest = orders.newest_first(session.id)
        view = timeline_view(session)
        return Response.page(session_page(library, session, view, newest_first=newest))

    def file(self, library: Library, request: Request) -> Response | None:
        """One file's changes, stacked: in one session (s=) or all; as a page, or as the
        drawer the session page opens (panel=1)."""
        path, session = request.param("path"), library.session(request.param("s"))
        everywhere = Stack.of(library.sessions, path)
        found = Stack.of([session], path) if session else everywhere
        if not path or not (found.changes or found.failed):
            return None
        render = file_panel if request.param("panel") == "1" else file_page
        oldest = request.param("order") == "oldest"
        return Response.page(render(library, found, session, len(everywhere.changes), oldest))

    def search(self, library: Library, request: Request) -> Response:
        where = next((w for w in WHERES if w == request.param("in")), None)
        results = Results.search(library.sessions, request.query, where)
        return Response.page(search_page(library, request.query, results, where))

    def knowledge(
        self, bench: Workbench, library: Library, rest: list[str], request: Request
    ) -> Response | None:
        store, param = bench.knowledge, request.param
        match rest, request.method:
            case [], "GET":
                return Response.page(
                    knowledge_page(
                        library,
                        store.all(),
                        param("view"),
                        param("scope"),
                        bench.provider,
                        Fresh.of(param("new"), param("merged"), param("extracted") == "1"),
                    )
                )
            case ["pick"], "GET":
                selected = set(request.params.get("s", []))
                return Response.page(
                    pick_page(library, selected, bench.provider, store.read_sessions())
                )
            case ["extract"], "POST":
                wanted = set(request.form.get("s", []))
                sessions = [s for s in library.sessions if s.id in wanted]
                if not sessions or not bench.ready():
                    first = sessions[0].id if sessions else ""
                    return Response.redirect(href("/knowledge/pick", s=first))
                return Response.redirect(bench.extract(sessions))
            case ["decide"], "POST":
                return Response.redirect(Decision.from_form(request.form).apply(store))
            case ["export"], "GET":
                return Response.page(export_page(library, store.all(), param("scope"), _today()))
            case ["export", name], "GET" if name in FILES.values():
                kind = next(k for k, file in FILES.items() if file == name)
                text = markdown(store.all(), kind, param("scope") or GLOBAL, _today())
                return Response.markdown(text, download=name)
        return None

    def library(self) -> Library:
        with self._lock:
            sessions = [session for source in self.sources for session in source.sessions()]
        knowledge = tuple(self.bench.knowledge.all()) if self.bench else ()
        return Library(sessions, knowledge)


@dataclass(frozen=True, slots=True)
class Decision:
    """What the review form decided: an action, the items it applies to, and any edits
    (statement, scope) that ride along; and the view to go back to."""

    action: str
    ids: list[int]
    edits: dict[int, tuple[str, str]]
    back: str

    @classmethod
    def from_form(cls, form: dict[str, list[str]]) -> "Decision":
        """Bulk (ticked ids and an action) or one row (its own button)."""

        def field(name: str) -> str:
            return form.get(name, [""])[0]

        edits = {
            int(number): (values[0], field(f"scope-{number}"))
            for key, values in form.items()
            if key.startswith("text-") and (number := key.removeprefix("text-")).isdigit()
        }
        if one := field("one"):
            action, _, number = one.partition(":")
            ids = [int(number)] if number.isdigit() else []
        else:
            action = field("action")
            ids = [int(i) for i in form.get("id", []) if i.isdigit()]
        if action == "save":
            ids = list(edits)
        view, marks = field("view"), Fresh.of(field("new"), field("merged")).to_params()
        back = href(
            "/knowledge", view="" if view == "review" else view, scope=field("scope"), **marks
        )
        return cls(action, ids, edits, back)

    def apply(self, store: KnowledgeStore) -> str:
        """Carry it out; returns where to go back to."""
        action = next((a for a in ACTIONS if a == self.action), None)
        if action and self.ids:
            edits = {i: e for i, e in self.edits.items() if i in self.ids}
            store.decide(self.ids, action, edits)
        return self.back


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _trusted(environ: WSGIEnvironment) -> bool:
    """Only this viewer's own pages may talk to it.

    The Host check stops DNS rebinding. For posts (a model call costs money), browsers
    say where a request comes from: Sec-Fetch-Site must be same-origin, or, in
    browsers without it, Origin must be this host. Origin can be "null" for
    same-origin posts under strict referrer policies, so Sec-Fetch-Site wins
    when present. Requests with neither header (curl) are allowed.
    """
    host = environ.get("HTTP_HOST", "127.0.0.1")
    if urlsplit(f"//{host}").hostname not in LOCAL_HOSTS:
        return False
    if environ.get("REQUEST_METHOD", "GET") in ("GET", "HEAD"):
        return True
    site = environ.get("HTTP_SEC_FETCH_SITE")
    if site is not None:
        return site in ("same-origin", "none")
    origin = environ.get("HTTP_ORIGIN")
    return origin is None or urlsplit(origin).netloc == host


def _form(environ: WSGIEnvironment) -> dict[str, list[str]]:
    try:
        length = min(int(environ.get("CONTENT_LENGTH") or 0), MAX_FORM)
    except ValueError:
        return {}
    raw = environ["wsgi.input"].read(length) if length else b""
    return parse_qs(raw.decode("utf-8", errors="replace"))


def _most_recent(sessions: list[Session]) -> Session | None:
    return max(sessions, key=lambda s: s.ended_at or s.started_at or "", default=None)


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class _ThreadingServer(ThreadingMixIn, WSGIServer):
    """One thread per request, so pages stay quick while a model works in the background."""

    daemon_threads = True


def serve(sources: Sequence[Source], port: int, bench: Workbench | None = None) -> None:
    """Serve on localhost only: sessions contain your code and your words."""
    with make_server(
        "127.0.0.1",
        port,
        Viewer(sources, bench=bench),
        server_class=_ThreadingServer,
        handler_class=_QuietHandler,
    ) as server:
        server.serve_forever()


def _cookies(header: str) -> dict[str, str]:
    """The browser's cookies for this viewer; a malformed header is no cookies."""
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(header)
    except CookieError:
        return {}
    return {name: morsel.value for name, morsel in jar.items()}
