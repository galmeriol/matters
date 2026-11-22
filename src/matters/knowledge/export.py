"""Accepted knowledge as Markdown: PREFERENCES.md and FACTS.md, for one scope.

Written to be read by an assistant at the start of a session: short sections by
category, one line per item, the reason where you gave one. No evidence or ids:
those stay in matters.
"""

from collections.abc import Sequence

from matters.knowledge.model import CATEGORIES, Item, Kind, scope_name

FILES: dict[Kind, str] = {"preference": "PREFERENCES.md", "fact": "FACTS.md"}
_INTRO: dict[Kind, str] = {
    "preference": "How I want things done. Follow these unless I say otherwise in the session.",
    "fact": "What is true, so you do not have to ask or guess. Tell me if something here is out of date.",
}


def markdown(items: Sequence[Item], kind: Kind, scope: str, date: str = "") -> str:
    chosen = [i for i in items if i.kind == kind and i.scope == scope and i.status == "accepted"]
    title = "Preferences" if kind == "preference" else "Facts"
    where = "" if scope_name(scope) == "global" else f": {scope_name(scope)}"
    lines = [f"# {title}{where}", "", _INTRO[kind]]
    if date:
        lines += ["", f"<!-- Vetted with matters; exported {date}. -->"]
    for category in (*CATEGORIES, *sorted({i.category for i in chosen} - set(CATEGORIES))):
        group = sorted((i for i in chosen if i.category == category), key=lambda i: i.id)
        if not group:
            continue
        lines += ["", f"## {category.capitalize()}", ""]
        lines += [f"- {i.statement.rstrip('.')}." + (f" ({i.why})" if i.why else "") for i in group]
    if len(lines) <= 3 + (2 if date else 0):
        lines += ["", "_Nothing accepted yet._"]
    return "\n".join(lines) + "\n"
