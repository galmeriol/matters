import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from matters.session import ToolCall
from matters.sources.claude_code import ClaudeCode
from matters.web import frame
from matters.web.app import CSP, Viewer
from matters.web.tool_views import BashView, EditView, ToolView, WriteView
from tests.fakes import FIXTURES


@pytest.fixture
def viewer() -> Viewer:
    return Viewer([ClaudeCode(root=FIXTURES / "claude")])


def text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def page(viewer: Viewer, path: str, query: str = "") -> str:
    response = viewer.route(path, query)
    assert response.status == "200 OK", response.status
    return response.body


def test_home_opens_the_most_recently_active_session(viewer: Viewer) -> None:
    response = viewer.route("/", "")
    assert response.status == "302 Found"
    assert ("Location", "/s/s3") in response.headers


def test_every_page_keeps_the_session_rail_with_the_current_session_marked(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    rail = html[html.index('<nav class="rail"') : html.index("</nav>")]
    assert re.findall(r": where it stands\">(cli|demo)</a>", rail) == ["cli", "demo"]
    assert rail.count("<li data-filter") == 3
    assert re.search(r'href="/s/s1" class="current" aria-current="page"', rail)
    assert 'class="rail"' in page(viewer, "/search", "q=x")


def test_search_finds_every_kind_of_text_and_opens_the_turn(viewer: Viewer) -> None:
    html = page(viewer, "/search", "q=signup")
    assert "in 1 of 3 sessions" in html
    assert "<mark>signup</mark>" in html
    assert 'href="/s/s1?hl=signup#t2"' in html  # the hit opens its turn, words marked
    assert ">You asked<" in html and ">Write<" in html  # an ask and a step of work
    assert page(viewer, "/", "q=signup") == html


def test_search_facets_narrow_to_asks_answers_or_work(viewer: Viewer) -> None:
    html = page(viewer, "/search", "q=signup&in=ask")
    assert "1 hit in asks" in html
    assert 'class="facet on" href="/search?q=signup&amp;in=ask"' in html
    assert ">Write<" not in html


def test_search_needs_every_word_in_the_same_block(viewer: Viewer) -> None:
    assert "Nothing matches" in page(viewer, "/search", "q=signup+slow")
    assert "<mark>test suite</mark>" in page(viewer, "/search", 'q="test suite"')


def test_a_project_name_opens_its_brief(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    assert '<a class="project-link" href="/p/demo"' in html
    assert re.search(r'<h2 class="label" data-n="2"><a href="/p/demo"', html)  # and in the rail
    brief = page(viewer, "/p/demo")
    assert "Where you left off" in brief and "Also cover the signup endpoint" in brief
    assert "Both endpoints are now limited." in brief
    assert 'href="/s/s2#t2"' in brief and "No answer" in brief  # s2 ended on an open ask
    assert "app/signup.rb" in brief and 'href="/s/s1#t2"' in brief
    assert viewer.route("/p/nowhere", "").status == "404 Not Found"


def test_the_brief_exports_as_markdown(viewer: Viewer) -> None:
    response = viewer.route("/p/demo.md", "")
    assert response.content_type.startswith("text/markdown")
    assert response.body.startswith("# demo\n")


def test_a_project_starts_folded_once_it_has_been_quiet_for_a_week(
    viewer: Viewer, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = viewer.library()
    s1, s3 = library.session("s1"), library.session("s3")
    assert s1 and s3 and s3.last_activity
    monkeypatch.setattr(frame, "now", lambda: s3.last_activity + timedelta(days=3))
    html = frame.rail(library, "/")
    assert '<details class="group" data-key="cli" data-open="1" open>' in html  # 3 days
    assert '<details class="group" data-key="demo" data-open="0">' in html  # 8 days
    # the project you are reading is open, however quiet
    reading = frame.rail(library, "/s/s1", s1)
    assert '<details class="group" data-key="demo" data-open="1" open>' in reading


def test_unfinished_sessions_are_marked_in_the_rail(viewer: Viewer) -> None:
    rail = page(viewer, "/s/s1")
    rail = rail[rail.index('<nav class="rail"') : rail.index("</nav>")]
    assert rail.count('class="loose"') == 1  # s2: its last ask got no answer


def test_turns_say_when_they_started_and_what_they_changed(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    assert '<div class="turn-meta"><time datetime="2026-11-10T09:02:00Z">' in html
    # a changed file opens its stack of changes, at this turn's layer
    assert 'href="/f?path=%2Ftmp%2Fdemo%2Fapp%2Fsignup.rb&amp;s=s1#L-s1-2" data-panel' in html
    # the files list says which turns edited each file
    refs = '<code>signup.rb</code></a><span class="turn-refs"><a href=#t2>2</a>'
    assert refs in html
    # files sit in a tree of their folders
    assert '<li class="folder"><details open><summary><span class="folder-name">app</span>' in html


def long_session(root: Path, turns: int) -> Viewer:
    """A session of `turns` turns: each edits one shared file, and turn 3 writes eight."""
    folder = root / "-p"
    folder.mkdir()
    lines = []
    for n in range(1, turns + 1):
        at = f"2026-11-10T{9 + n // 60:02d}:{n % 60:02d}:00Z"
        writes = [f"/p/src/w{i}.py" for i in range(8)] if n == 3 else []
        uses = [
            {
                "type": "tool_use",
                "id": f"e{n}",
                "name": "Edit",
                "input": {
                    "file_path": "/p/src/shared.py",
                    "old_string": "a",
                    "new_string": f"a{n}",
                },
            }
        ]
        uses += [
            {
                "type": "tool_use",
                "id": f"w{n}-{i}",
                "name": "Write",
                "input": {"file_path": w, "content": "x"},
            }
            for i, w in enumerate(writes)
        ]
        lines.append(
            {
                "type": "user",
                "timestamp": at,
                "cwd": "/p",
                "message": {"content": f"ask number {n}"},
            }
        )
        lines.append({"type": "assistant", "timestamp": at, "message": {"content": uses}})
        lines.append(
            {
                "type": "assistant",
                "timestamp": at,
                "message": {"content": [{"type": "text", "text": f"answer {n}"}]},
            }
        )
    (folder / "long.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return Viewer([ClaudeCode(root=root)])


def test_a_long_session_folds_everything_after_its_first_turns(tmp_path: Path) -> None:
    html = page(long_session(tmp_path, 25), "/s/long")
    chapters = re.findall(r'<details class="chapter" id="turns-(\d+)"( open)?>', html)
    assert chapters == [("1", " open"), ("4", ""), ("14", ""), ("24", "")]
    assert '<span class="chapter-name">Turns 4–13</span>' in html
    # every turn is still on the page, so links, find and search marks reach it
    assert all(f'id="t{n}"' in html for n in range(1, 26))


def test_newest_first_opens_the_newest_turns_and_folds_back_from_them(tmp_path: Path) -> None:
    html = long_session(tmp_path, 25).route("/s/long", "", cookie="matters-order=newest").body
    chapters = re.findall(r'<details class="chapter" id="turns-(\d+)"( open)?>', html)
    assert chapters == [("23", " open"), ("13", ""), ("3", ""), ("1", "")]
    turns = [int(n) for n in re.findall(r'<section class="turn[^"]*" id="t(\d+)"', html)]
    assert turns == list(range(25, 0, -1))
    index = html[html.index('class="turn-list"') :]
    assert index.startswith('class="turn-list" reversed>')
    assert index.index('href="#t25"') < index.index('href="#t1"')


def test_the_newest_turn_is_always_a_click_away(tmp_path: Path) -> None:
    viewer = long_session(tmp_path, 25)
    for order, arrow in (("oldest", "↓"), ("newest", "↑")):
        html = viewer.route("/s/long", "", cookie=f"matters-order={order}").body
        assert '<a class="to-newest" href="#t25"' in html and f"Newest turn, 25 {arrow}" in html
        assert 'data-newest="25"' in html


def order_of(viewer: Viewer, session: str, cookie: str = "") -> str:
    body = viewer.route(f"/s/{session}", "", cookie=cookie).body
    return re.search(r'<article class="turns" data-order="(\w+)"', body)[1]  # type: ignore[index]


def test_an_order_picked_on_a_session_is_for_that_session_alone(viewer: Viewer) -> None:
    picked = viewer.route("/s/s1", "order=newest")
    assert picked.status == "303 See Other" and ("Location", "/s/s1") in picked.headers
    kept = "matters-turns=s1:n; Path=/; Max-Age=31536000; SameSite=Strict"
    assert ("Set-Cookie", kept) in picked.headers
    assert order_of(viewer, "s1", "matters-turns=s1:n") == "newest"
    assert order_of(viewer, "s2", "matters-turns=s1:n") == "oldest"


def test_a_session_set_on_its_own_keeps_its_order_whatever_the_default(viewer: Viewer) -> None:
    both = "matters-order=newest; matters-turns=s1:o"
    assert order_of(viewer, "s1", both) == "oldest"
    assert order_of(viewer, "s2", both) == "newest"
    # picking the default again lets the session follow the default: the pick is cleared
    back = viewer.route("/s/s1", "order=newest", cookie=both)
    cleared = "matters-turns=; Path=/; Max-Age=0; SameSite=Strict"
    assert ("Set-Cookie", cleared) in back.headers


def test_nothing_picked_or_nonsense_reads_from_the_first_turn(viewer: Viewer) -> None:
    for query, cookie in (
        ("", ""),
        ("order=sideways", "matters-order=sideways; matters-turns=s1:x.<b>:n"),
        ("", 'matters-turns="broken'),
    ):
        response = viewer.route("/s/s1", query, cookie=cookie)
        assert response.status == "200 OK" and not response.headers
        assert 'data-order="oldest"' in response.body


def test_the_picks_fit_in_a_cookie_and_the_latest_stay() -> None:
    from matters.web.orders import ROOM, TurnOrders

    orders = TurnOrders()
    for n in range(300):
        orders = orders.picking(f"{n:08d}-aaaa-bbbb-cccc-dddddddddddd", "newest")
    assert len(orders.to_cookie()) < ROOM + 100
    assert orders.newest_first(f"{299:08d}-aaaa-bbbb-cccc-dddddddddddd")
    assert not orders.newest_first(f"{0:08d}-aaaa-bbbb-cccc-dddddddddddd")


def test_the_settings_menu_sets_the_order_for_every_session(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    menu = html[html.index('<details class="settings"') :]
    assert "<legend>Turns</legend>" in menu
    assert 'name="order" value="oldest"' in menu and 'name="order" value="newest"' in menu


def test_a_session_of_eight_turns_or_fewer_does_not_fold(tmp_path: Path) -> None:
    assert 'class="chapter"' not in page(long_session(tmp_path, 8), "/s/long")


def test_a_short_session_has_no_chapters(viewer: Viewer) -> None:
    assert 'class="chapter"' not in page(viewer, "/s/s1")


def test_long_lists_beside_a_file_and_a_turn_are_capped(tmp_path: Path) -> None:
    html = page(long_session(tmp_path, 25), "/s/long")
    # shared.py was edited in all 25 turns: four turn numbers, the rest in its stack
    assert re.search(
        r'<code>shared\.py</code></a><span class="turn-refs">(<a href=#t\d+>\d+</a>){4}'
        r'<a class="more-refs" [^>]*>\+21</a>',
        html,
    )
    # turn 3 changed nine files: six named, three folded, in a block that can hold the
    # fold (a <details> in a <p> is moved out of it by the parser), apart so they wrap
    assert '<details class="more-files"><summary>+3 more</summary>' in html
    assert '<p class="turn-meta">' not in html
    folded = re.search(r'class="more-files"><summary>\+3 more</summary>(.*?)</details>', html)
    assert folded and folded.group(1).count("</a> <a") == 2
    # the index offers turns and files as parts the page script makes into tabs
    assert 'data-tab="Turns" data-count="25"' in html and 'data-tab="Files" data-count="9"' in html


def test_a_tree_shows_a_chain_of_single_folders_as_one(tmp_path: Path) -> None:
    html = page(long_session(tmp_path, 3), "/s/long")
    # every file is under /p/src: one folder row, holding all nine
    assert (
        '<span class="folder-name">src</span><span class="count" title="9 edited">9</span>' in html
    )


def test_stack_layers_are_numbered_by_the_turn_that_made_them(tmp_path: Path) -> None:
    viewer = long_session(tmp_path, 14)
    html = page(viewer, "/f", "path=/p/src/shared.py&s=long")
    nodes = re.findall(r'<span class="node[^"]*" title="Turn (\d+)[^"]*">', html)
    assert nodes == [str(n) for n in range(14, 0, -1)]


def test_the_header_says_how_the_session_ended(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    assert '<p class="ended"><b>Ended</b>with an answer; nothing was left open.' in html


def test_the_header_labels_each_figure_and_links_to_where_it_is_taken_apart(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    glance = html[html.index('<nav class="glance"') :]
    glance = glance[: glance.index("</nav>")]
    labels = re.findall(r'<span class="g-label">([^<]+)</span>', glance)
    assert labels[:3] == ["Work time", "Asks", "Files changed"]
    assert 'href="#index-files"' in glance and 'href="#timeline"' in glance
    assert '<span class="plus">+2</span>' in glance  # a line from each change


def test_the_lanes_say_how_to_read_them(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    assert '<details class="timeline" id="timeline" open>' in html
    assert "Each row is one kind of work" in html
    assert '<span class="tl-col pct">share</span>' in html
    # each mark carries where it sits in seconds, so the page script can zoom the chart
    assert re.search(r'<div class="tl-grid" [^>]*data-total="\d+\.\d{3}"', html)
    assert re.search(
        r'class="tl-seg[^"]*" href="#t\d+" draggable="false" '
        r'data-start="[\d.]+" data-seconds="[\d.]+"',
        html,
    )


def test_code_in_answers_is_highlighted_in_ink() -> None:
    from matters.web.markdown import render_markdown

    html = render_markdown("```python\ndef f():\n    return 1\n```", Path("/p"))
    assert '<pre class="hl" data-lang="python"><code>' in html
    assert '<span class="k">def</span>' in html
    plain = render_markdown("```\nplain\n```", Path("/p"))
    assert "<pre><code>plain" in plain


def test_a_turn_shows_ask_folded_work_answer_and_events(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    assert html.count('class="turn"') == 2
    assert "2 steps — Edit 1" in text(html)
    assert "Both endpoints are now limited." in html
    assert "1 failed" in html
    assert "/clear" in html
    assert "claude --resume s1" in html


def test_answers_are_rendered_as_markdown(viewer: Viewer) -> None:
    html = page(viewer, "/s/s3")
    assert "<strong>Next</strong>" in html
    assert 'href="vscode://file/tmp/cli/app.py:3"' in html


def test_cli_context_gets_its_own_shapes(viewer: Viewer) -> None:
    html = page(viewer, "/s/s3")
    assert '<a class="chip" href="vscode://file/tmp/cli/app.py"' in html
    assert "app.py L3–5" in html
    assert '<details class="paste">' in html and "3 lines" in html
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in html
    assert "<code>/model opus</code>" in html and "Set model to opus" in html
    assert "Interrupted by you" in html
    assert "Tests finished" in html


def test_escapes_everything_from_sessions(tmp_path: Path) -> None:
    folder = tmp_path / "-p"
    folder.mkdir()
    (folder / "x.jsonl").write_text(
        '{"type":"user","cwd":"/p","message":{"content":"hi <script>alert(1)</script>"}}\n'
        '{"type":"assistant","message":{"content":'
        '[{"type":"text","text":"<img src=x onerror=alert(1)>"}]}}\n'
    )
    html = page(Viewer([ClaudeCode(root=tmp_path)]), "/s/x")
    body = html[html.index("<main") :]
    assert "<script>alert(1)" not in body
    assert "<img src=x" not in body
    assert "&lt;script&gt;alert(1)" in body


def test_unknown_paths_and_sessions_are_404(viewer: Viewer) -> None:
    assert viewer.route("/s/nope", "").status == "404 Not Found"
    assert viewer.route("/etc/passwd", "").status == "404 Not Found"


def test_wsgi_call_sends_html_with_a_strict_content_security_policy(viewer: Viewer) -> None:
    seen: list[tuple[str, list[tuple[str, str]]]] = []
    body = b"".join(
        viewer(
            {"PATH_INFO": "/s/s1"},
            lambda status, headers: seen.append((status, headers)),  # type: ignore[arg-type]
        )
    )
    status, headers = seen[0]
    assert status == "200 OK"
    assert ("Content-Security-Policy", CSP) in headers
    assert "default-src 'none'" in CSP
    assert body.startswith(b"<!doctype html>")


def test_each_tool_gets_its_own_view_and_unknown_tools_the_generic_one() -> None:
    project = Path("/p")
    assert type(ToolView.for_(ToolCall("Bash"), project)) is BashView
    assert type(ToolView.for_(ToolCall("Write"), project)) is WriteView
    assert type(ToolView.for_(ToolCall("SomethingNew", {"x": "y"}), project)) is ToolView


def test_edits_read_as_diffs_with_paths_relative_to_the_project() -> None:
    view = EditView(
        ToolCall("Edit", {"file_path": "/p/a.py", "old_string": "x = 1", "new_string": "x = 2"}),
        Path("/p"),
    )
    assert view.summary() == "a.py"
    assert '<span class="del">-x = 1</span>' in view.body()
    assert '<span class="add">+x = 2</span>' in view.body()


def test_bash_reads_as_a_command_with_its_output() -> None:
    view = BashView(
        ToolCall("Bash", {"command": "ls -la", "description": "List files"}, "a\nb"), Path("/p")
    )
    assert view.summary() == "List files"
    assert "$ ls -la" in view.body()
    assert "a\nb" in view.body()


def test_a_file_opens_its_changes_stacked_latest_on_top(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    assert 'href="/f?path=%2Ftmp%2Fdemo%2Fapp%2Flogin.rb&amp;s=s1" data-panel' in html  # index
    stack = page(viewer, "/f", "path=/tmp/demo/app/login.rb&s=s1")
    assert "1 change in this session" in stack and "1 failed edit not shown" in stack
    assert stack.count('class="layer"') == 1 and 'id="L-s1-1"' in stack
    assert '<span class="add">+before_action :throttle</span>' in stack  # the edit that worked
    assert "Add rate limiting to the login endpoint" in stack  # the ask that led to it
    assert 'href="/s/s1#t1"' in stack


def test_the_drawer_gets_the_stack_without_the_page_around_it(viewer: Viewer) -> None:
    panel = page(viewer, "/f", "path=/tmp/demo/app/signup.rb&s=s1&panel=1")
    assert not panel.startswith("<!doctype") and 'class="panel-close"' in panel
    assert 'class="stack"' in panel and "Wrote the file · 1 lines" in panel


def test_without_a_session_the_stack_spans_every_session(viewer: Viewer) -> None:
    stack = page(viewer, "/f", "path=/tmp/demo/app/signup.rb")
    assert "in 1 session" in stack and 'class="stack-session"' in stack
    assert viewer.route("/f", "path=/nowhere.py").status == "404 Not Found"
    assert 'href="/f?path=%2Ftmp%2Fdemo%2Fapp%2Fsignup.rb"' in page(viewer, "/p/demo")


def test_the_lanes_can_be_shaded_by_token_use(viewer: Viewer) -> None:
    html = page(viewer, "/s/s1")
    tokens = re.findall(r'class="tl-seg[^"]*"[^>]*data-tokens="(\w+)"', html)
    assert tokens and set(tokens) <= {"none", "low", "medium", "high"}
    assert "none" in tokens  # your own time takes no tokens
    assert '<div class="tl-shade" hidden>' in html  # the page script shows the switch
    assert 'd.dataset.shade="tokens"' in html  # the choice is applied before paint
