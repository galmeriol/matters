from pathlib import Path

from matters.web.markdown import render_markdown

PROJECT = Path("/work/app")


def render(text: str) -> str:
    return render_markdown(text, PROJECT)


def test_renders_the_markdown_assistants_write() -> None:
    html = render(
        "## Plan\n\n- **one**\n- `two`\n\n```py\nx = 1\n```\n\n| a | b |\n| - | - |\n| 1 | 2 |"
    )
    assert "<h2>Plan</h2>" in html
    assert "<strong>one</strong>" in html
    assert "<code>two</code>" in html
    assert '<pre class="hl" data-lang="py"><code><span class="n">x</span>' in html
    assert "<table>" in html


def test_escapes_raw_html_instead_of_rendering_it() -> None:
    html = render("hi <script>alert(1)</script> <img src=x onerror=alert(1)>")
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html


def test_refuses_script_links() -> None:
    assert 'href="javascript' not in render("[x](javascript:alert(1))")


def test_project_relative_links_open_in_the_editor_at_the_line() -> None:
    assert 'href="vscode://file/work/app/src/a.py:42"' in render("[a.py:42](src/a.py#L42)")
    assert 'href="vscode://file/work/app/src/a.py:42"' in render("[range](src/a.py#L42-L51)")
    assert 'href="vscode://file/work/app/docs"' in render("[docs](docs/)")
    assert 'href="vscode://file/etc/hosts"' in render("[abs](/etc/hosts)")


def test_web_links_open_in_a_new_tab() -> None:
    html = render("[site](https://example.com)")
    assert 'href="https://example.com"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
