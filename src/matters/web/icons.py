"""A small inline SVG icon set, drawn for this viewer: one sprite per page, used by id.

Icons are strokes in currentColor, so they follow the text colour in both themes.
"""

from urllib.parse import quote

_PATHS = {
    "paste": '<rect x="8" y="2.5" width="8" height="4" rx="1"/>'
    '<path d="M16 4.5h2a2 2 0 0 1 2 2V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6.5a2 2 0 0 1 2-2h2"/>'
    '<path d="M8.5 12h7M8.5 16h5"/>',
    "file": '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/>'
    '<path d="M14 2.5V8h5.5"/>',
    "selection": '<path d="M5 4.5h3M5 19.5h3M6.5 4.5v15"/><path d="M11 8h8M11 12h8M11 16h5"/>',
    "image": '<rect x="3" y="3.5" width="18" height="17" rx="1.5"/><circle cx="9" cy="9.5" r="1.8"/>'
    '<path d="m21 15.5-5-5-11 10"/>',
    "terminal": '<path d="m4.5 7 5 5-5 5"/><path d="M12 18h7.5"/>',
    "stop": '<circle cx="12" cy="12" r="9"/><rect x="9" y="9" width="6" height="6"/>',
    "bell": '<path d="M6.5 9a5.5 5.5 0 0 1 11 0c0 6 2.5 8 2.5 8H4s2.5-2 2.5-8"/>'
    '<path d="M10.3 20.5a1.9 1.9 0 0 0 3.4 0"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16.5v-5M12 8h.01"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20.5 20.5-4.8-4.8"/>',
    "menu": '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
    # appearance: two sliders
    "sliders": '<path d="M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9"/><circle cx="15" cy="7.5" r="2"/><circle cx="9" cy="16.5" r="2"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
    "chevron": '<path d="m9.5 6 6 6-6 6"/>',
    "bulb": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>',
    "bookmark": '<path d="M6.5 3.5h11v17l-5.5-4-5.5 4z"/>',
    "download": '<path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
    "map": '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.3 11 15.7 7M8.3 13l7.4 4"/>',
    # a run handed off: the main line, and a branch that goes off to work on its own
    "agent": '<circle cx="6" cy="5.5" r="2.2"/><circle cx="6" cy="18.5" r="2.2"/><circle cx="18" cy="12" r="2.2"/>'
    '<path d="M6 7.7v8.6M6 10.5c0 1.5 1 2.5 3 2.5h6.8"/>',
    "tasks": '<path d="m4 6.5 1.6 1.6L8.5 5M4 13.5l1.6 1.6 2.9-3.1"/><path d="M11.5 7h8.5M11.5 14h8.5"/>'
    '<rect x="4" y="18" width="4" height="3" rx=".6"/><path d="M11.5 19.5h8.5"/>',
}

SPRITE = (
    '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
    + "".join(
        f'<symbol id="i-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths}</symbol>'
        for name, paths in _PATHS.items()
    )
    + "</svg>"
)


# The mark: an M whose valley is a mind-map node (a ring where the strokes meet), standing
# on a ledger rule. Ink tile on paper; inverted in dark mode. Inline, so the CSP's
# img-src data: allows it.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><style>'
    ".t{fill:#121212}.m{stroke:#fbfbf8;fill:none}.n{fill:#121212;stroke:#fbfbf8}"
    "@media (prefers-color-scheme:dark){.t{fill:#ecece6}.m{stroke:#121212}"
    ".n{fill:#ecece6;stroke:#121212}}</style>"
    '<rect class="t" width="32" height="32" rx="6"/>'
    '<path class="m" d="M8 24V8.5l8 10 8-10V24" stroke-width="3.4" stroke-linecap="square"/>'
    '<circle class="n" cx="16" cy="18.5" r="3" stroke-width="2.2"/>'
    '<path class="m" d="M5.5 27.5h21" stroke-width="1.6"/></svg>'
)
FAVICON = "data:image/svg+xml," + quote(FAVICON_SVG)


def mark(*classes: str) -> str:
    """The same mark, inline: drawn with the page's colour tokens, so it follows the theme.
    `pathLength` lets the stylesheet draw the M stroke by stroke (the loading state)."""
    names = " ".join(("mark", *classes))
    return (
        f'<svg class="{names}" viewBox="0 0 32 32" aria-hidden="true">'
        '<rect class="mark-tile" width="32" height="32" rx="6"/>'
        '<path class="mark-m" d="M8 24V8.5l8 10 8-10V24" pathLength="1"/>'
        '<circle class="mark-node" cx="16" cy="18.5" r="3"/>'
        '<path class="mark-rule" d="M5.5 27.5h21" pathLength="1"/></svg>'
    )


def icon(name: str) -> str:
    if name not in _PATHS:
        raise KeyError(f"No icon named {name!r}")
    return f'<svg class="icon" aria-hidden="true"><use href="#i-{name}"/></svg>'
