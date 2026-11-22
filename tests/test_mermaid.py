"""Mermaid diagrams: drawn by a bundled, pinned script, loaded only where needed."""

import hashlib
import re
from importlib.resources import files
from pathlib import Path

from matters.web.app import CSP, MERMAID, Viewer
from matters.web.frame import SCRIPT
from matters.web.markdown import render_markdown
from tests.fakes import FakeSource

CHECKSUM = "a43bc1afd446f9c4cc66ac5dd45d02e8d65e26fc5344ec0ef787f88d6ddb6f9e"
DIAGRAM = "```mermaid\ngraph TD\n  A[api] --> B<br>{cache}\n```"


def test_mermaid_blocks_become_figures_with_their_source_behind_a_toggle() -> None:
    html = render_markdown(DIAGRAM, Path())
    assert '<figure class="mermaid-figure"><pre class="mermaid">graph TD' in html
    assert "B&lt;br&gt;{cache}" in html  # escaped: Mermaid reads the text, not markup
    assert '<details class="mermaid-source">' in html
    assert "<br>" not in html


def test_other_blocks_are_untouched() -> None:
    assert "mermaid" not in render_markdown("```python\nx = 1\n```", Path())


def test_the_bundled_script_is_the_pinned_one() -> None:
    script = files("matters.web").joinpath("vendor", MERMAID).read_bytes()
    assert hashlib.sha256(script).hexdigest() == CHECKSUM
    assert f"/static/{MERMAID}" in SCRIPT  # the page loads the same file the server serves


def test_it_is_served_from_here_and_only_it() -> None:
    app = Viewer([FakeSource([])])
    response = app.route(f"/static/{MERMAID}", "")
    assert response.status == "200 OK" and response.content_type.startswith("text/javascript")
    assert ("Cache-Control", "max-age=31536000, immutable") in response.headers
    assert app.route("/static/other.js", "").status == "404 Not Found"
    assert app.route("/static/..%2Fapp.py", "").status == "404 Not Found"


def test_the_policy_allows_scripts_from_this_viewer_and_nowhere_else() -> None:
    sources = re.search(r"script-src ([^;]+)", CSP)
    assert sources is not None and sources.group(1).split() == ["'self'", "'unsafe-inline'"]
