"""Markdown for what the assistant wrote. Raw HTML is escaped, never rendered.

Links are rewritten for this viewer: a project-relative link such as
`[a.py:42](src/a.py#L42)` would 404 here, so it opens the file in VS Code at
that line instead; web links open in a new tab.

Fenced blocks with a language are highlighted in ink (weight and slant, not colour:
see `.hl` in style.css), so code reads like code without breaking the page's palette.

Mermaid blocks are drawn: a `pre.mermaid` the page script hands to the bundled
Mermaid (strict mode), with the source one click away. Without the script, the
source is what shows.
"""

import re
from collections.abc import Sequence
from html import escape
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererProtocol
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_LINE = re.compile(r"^L(\d+)")
_FORMATTER = HtmlFormatter(nowrap=True)
MAX_HIGHLIGHT = 60_000  # characters: past this, plain text is faster to read than to wait for


def render_markdown(text: str, project: Path) -> str:
    return str(_MD.render(text, {"project": project}))


def highlighted(code: str, lang: str) -> str:
    """Code as HTML, highlighted when the language is known; escaped text otherwise."""
    lexer = _lexer(lang)
    if lexer is None or len(code) > MAX_HIGHLIGHT:
        return escape(code)
    return str(highlight(code, lexer, _FORMATTER))


def _lexer(lang: str) -> Lexer | None:
    if not lang:
        return None
    try:
        return get_lexer_by_name(lang)
    except ClassNotFound:
        return None


def _language(token: Token) -> str:
    return token.info.strip().split(maxsplit=1)[0] if token.info.strip() else ""


def _fence(
    self: RendererProtocol, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
) -> str:
    token = tokens[idx]
    lang = _language(token)
    if lang.lower() == "mermaid":
        return mermaid_figure(token.content, str(_DEFAULT_FENCE(tokens, idx, options, env)))
    data = f' data-lang="{escape(lang)}"' if lang else ""
    css = ' class="hl"' if _lexer(lang) else ""
    return f"<pre{css}{data}><code>{highlighted(token.content, lang)}</code></pre>\n"


def _link_open(
    self: RendererProtocol, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
) -> str:
    token = tokens[idx]
    href = str(token.attrGet("href") or "")
    if _SCHEME.match(href):
        if href.startswith(("http:", "https:")):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener noreferrer")
    elif href and not href.startswith("#"):
        token.attrSet("href", _editor_link(href, env["project"]))
    return self.renderToken(tokens, idx, options, env)  # type: ignore[attr-defined,no-any-return]


def _editor_link(href: str, project: Path) -> str:
    path, _, fragment = href.partition("#")
    target = Path(unquote(path))
    absolute = target if target.is_absolute() else project / target
    line = _LINE.match(fragment)
    return f"vscode://file{absolute}" + (f":{line.group(1)}" if line else "")


def mermaid_figure(source: str, source_html: str) -> str:
    """A diagram to draw, and its source behind a toggle."""
    return (
        f'<figure class="mermaid-figure"><pre class="mermaid">{escape(source)}</pre></figure>'
        f'<details class="mermaid-source"><summary>Mermaid source</summary>{source_html}</details>'
    )


def _build() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    md.add_render_rule("link_open", _link_open)
    return md


_MD = _build()
_DEFAULT_FENCE = _MD.renderer.rules["fence"]  # type: ignore[attr-defined]
_MD.add_render_rule("fence", _fence)
