"""Claude Code's conventions for what it adds around the human's words.

The CLI and IDE extensions wrap context in tags inside user messages. This
module turns them into provider-neutral Parts; nothing outside the Claude
adapter knows these tag names.
"""

import re
from pathlib import PurePath

from matters.session import Part

_CONTEXT = re.compile(
    r"<(pasted_content|ide_opened_file|ide_selection|system-reminder|task-notification)\b[^>]*>"
    r"(.*?)</\1(?:\s[^>]*)?>",  # the IDE repeats attributes on some closing tags
    re.S,
)
_IMAGE_MARK = re.compile(r"^\[Image[^\]\n]*\]$", re.M)
_COMMAND = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_BASH = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
_OUTPUT = re.compile(
    r"<(local-command-stdout|local-command-stderr|bash-stdout|bash-stderr)>(.*?)</\1>", re.S
)
_OPENED = re.compile(r"opened the file (.+?) in the IDE")
_SELECTED_FROM = re.compile(r"from (\S+?):?\s")
_LINES = re.compile(r"lines? (\d+)(?: to (\d+))?")
_TAG = re.compile(r"<(summary|status)>(.*?)</\1>", re.S)

TYPED = frozenset({"text", "pasted", "image"})


def command(text: str) -> str | None:
    """'/name args' for a slash command, '! cmd' for bash mode, else None."""
    if name := _COMMAND.search(text):
        args = _ARGS.search(text)
        return f"{name.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    if bash := _BASH.search(text):
        return f"! {bash.group(1).strip()}"
    return None


def command_output(text: str) -> str | None:
    outputs = [m.group(2).strip() for m in _OUTPUT.finditer(text)]
    return "\n".join(o for o in outputs if o) if outputs else None


def message_parts(text: str, *, has_images: bool) -> list[Part]:
    """Split one text block into the human's words and the context around them, in order."""
    parts: list[Part] = []
    position = 0
    for match in _CONTEXT.finditer(text):
        parts.extend(_words(text[position : match.start()], has_images))
        parts.append(_context(match.group(1), match.group(2)))
        position = match.end()
    parts.extend(_words(text[position:], has_images))
    return parts


_NOTIFICATION = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
_FIELD = re.compile(r"<([a-z][a-z_-]*)>(.*?)</\1>", re.S)


def notifications(text: str) -> list[dict[str, str]]:
    """Each background-task notice in a message, as its fields: task-id, tool-use-id,
    status, summary, result, and the figures inside <usage> (subagent_tokens, tool_uses,
    duration_ms) lifted to the top."""
    found = []
    for match in _NOTIFICATION.finditer(text):
        fields: dict[str, str] = {}
        for tag, body in _FIELD.findall(match.group(1)):
            fields[tag] = body.strip()
            if tag == "usage":
                fields.update((t, b.strip()) for t, b in _FIELD.findall(body))
        found.append(fields)
    return found


def ask_text(parts: list[Part]) -> str:
    """The ask as one plain string, for search and maps: words in full, the rest as labels."""
    pieces = []
    for part in parts:
        if part.kind == "text":
            pieces.append(part.text)
        elif part.kind == "pasted":
            pieces.append(f"[Pasted text · {part.label}]")
        elif part.kind == "image":
            pieces.append("[Image]")
    return " ".join(pieces).strip()


def _words(chunk: str, has_images: bool) -> list[Part]:
    parts = []
    if not has_images:
        parts = [Part("image", label=m.group(0)[1:-1]) for m in _IMAGE_MARK.finditer(chunk)]
    words = _IMAGE_MARK.sub("", chunk).strip()
    return parts + ([Part("text", words)] if words else [])


def _context(tag: str, body: str) -> Part:
    body = body.strip("\n")
    match tag:
        case "pasted_content":
            lines = body.count("\n") + 1
            return Part("pasted", body, f"{lines} line{'s' if lines != 1 else ''}")
        case "ide_opened_file":
            opened = _OPENED.search(body)
            return Part("file", opened.group(1) if opened else "", "Opened file")
        case "ide_selection":
            return Part("selection", body, _selection_label(body))
        case "task-notification":
            fields = {m.group(1): m.group(2).strip() for m in _TAG.finditer(body)}
            label = fields.get("summary") or fields.get("status") or "Background task"
            return Part("notification", body, label)
        case _:
            return Part("reminder", body.strip(), "System reminder")


def _selection_label(body: str) -> str:
    source = _SELECTED_FROM.search(body)
    lines = _LINES.search(body)
    name = PurePath(source.group(1)).name if source else "Selection"
    if not lines:
        return name
    end = f"–{lines.group(2)}" if lines.group(2) and lines.group(2) != lines.group(1) else ""
    return f"{name} L{lines.group(1)}{end}"
