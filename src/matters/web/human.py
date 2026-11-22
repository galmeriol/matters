"""What the human sent, and what happened in the tool: asks with their context,
commands, interruptions and notices. Each kind of Part keeps its own shape."""

from html import escape
from pathlib import Path, PurePath

from matters.links import editor_url
from matters.session import Entry, Part
from matters.web.icons import icon

CLIP = 20_000
CHIPS = frozenset({"file", "selection", "reminder", "notification", "queued"})
ICONS = {
    "file": "file",
    "selection": "selection",
    "reminder": "info",
    "notification": "bell",
    "image": "image",
    "pasted": "paste",
    "queued": "clock",
}


def ask_html(entry: Entry) -> str:
    parts = entry.parts or (Part("text", entry.text),)
    chips = [_chip(p) for p in parts if p.kind in CHIPS or (p.kind == "image" and not p.media_type)]
    body = "".join(_body_part(p) for p in parts if p.kind not in CHIPS and _has_body(p))
    chip_row = f'<div class="chips">{"".join(chips)}</div>' if chips else ""
    return f'<div class="ask">{source(entry)}{chip_row}{body}</div>'


def event_html(entry: Entry) -> str:
    match entry.kind:
        case "command":
            output = next((p.text for p in entry.parts if p.kind == "output"), "")
            label = f"{icon('terminal')}<code>{escape(entry.text)}</code>"
            if not output:
                return f'<div class="event command">{label}{source(entry)}</div>'
            return (
                f'<details class="event command"><summary>{label}'
                f'<span class="meta">output</span>{source(entry)}</summary>{_pre(output)}</details>'
            )
        case "interrupt":
            return f'<div class="event interrupt">{icon("stop")}Interrupted by you{source(entry)}</div>'
        case _:
            first = entry.parts[0].kind if entry.parts else "notification"
            body = "".join(_pre(p.text) for p in entry.parts if p.text)
            return (
                f'<details class="event notice"><summary>{icon(ICONS.get(first, "bell"))}'
                f"{escape(entry.text)}{source(entry)}</summary>{body}</details>"
            )


def source(entry: Entry) -> str:
    return (
        f'<a class="src" href="{escape(editor_url(entry.ref))}" '
        f'title="Open the source line in VS Code">line {entry.ref.line}</a>'
    )


def _has_body(part: Part) -> bool:
    return part.kind != "image" or bool(part.media_type)


def _body_part(part: Part) -> str:
    match part.kind:
        case "pasted":
            preview = next((line.strip() for line in part.text.splitlines() if line.strip()), "")
            return (
                f'<details class="paste"><summary>{icon("paste")}<b>Pasted text</b>'
                f'<span class="meta">{escape(part.label)}</span>'
                f'<span class="preview">{escape(preview[:120])}</span></summary>{_pre(part.text)}</details>'
            )
        case "image":
            src = f"data:{part.media_type};base64,{part.text}"
            return (
                f'<button type="button" class="thumb" title="Click to enlarge">'
                f'<img src="{escape(src)}" alt="Image you attached" loading="lazy"></button>'
            )
        case _:
            return f'<div class="words">{escape(part.text)}</div>'


def _chip(part: Part) -> str:
    glyph = icon(ICONS[part.kind])
    if part.kind == "file":
        name = PurePath(part.text).name or part.label
        href = escape(f"vscode://file{Path(part.text)}")
        return (
            f'<a class="chip" href="{href}" title="{escape(part.text)}">{glyph}{escape(name)}</a>'
        )
    if part.kind in ("image", "queued"):
        return f'<span class="chip {part.kind}">{glyph}{escape(part.label)}</span>'
    return f'<details class="chip {part.kind}"><summary>{glyph}{escape(part.label)}</summary>{_pre(part.text)}</details>'


def _pre(text: str) -> str:
    shown = text[:CLIP]
    more = len(text) - len(shown)
    note = f'<p class="quiet">… {more:,} more characters in the source.</p>' if more > 0 else ""
    return f"<pre>{escape(shown)}</pre>{note}"
