"""Every theme, light and dark, must stay legible and keep what its colours mean.

- Text meets WCAG AAA (7:1) on the background it sits on.
- Marks that aren't text (timeline lanes, the running pulse) meet 3:1 (WCAG non-text).
- Status keeps its own hue: a failure, something running, a search hit and where you are
  never look alike, and accents stay clear of them.
"""

import colorsys
import re
from importlib.resources import files
from itertools import pairwise

import pytest

from matters.web.frame import THEMES

CSS = files("matters.web").joinpath("style.css").read_text(encoding="utf-8")
HEX = r"#[0-9a-fA-F]{6}"

# (text, background)
TEXT = [
    ("ink", "paper"), ("ink", "sheet"), ("ink", "code"), ("ink", "mark"), ("ink", "rail-bg"),
    ("ink-2", "paper"), ("ink-2", "sheet"), ("ink-2", "code"), ("ink-2", "rail-bg"),
    ("accent", "paper"), ("accent", "sheet"),
    ("err", "paper"), ("err", "sheet"),
    ("add-ink", "add-bg"), ("del-ink", "del-bg"), ("add-ink", "paper"), ("add-ink", "sheet"),
    ("live", "paper"), ("live", "sheet"),  # "Running", "running"
    ("sel-ink", "sel-bg"),  # where you are: the current session, the open tab
    ("ink", "card"), ("ink-2", "card"),  # the rail's card for the session you are reading
]  # fmt: skip
# Drawn shapes, not text: (mark, background)
SHAPES = [
    ("lane", "sheet"), ("lane", "paper"), ("live", "paper"), ("live", "rail-bg"),
    ("lane-lo", "sheet"), ("lane-lo", "paper"),  # the lightest shade of token use
]  # fmt: skip
# Meanings that must not look alike.
APART = [
    ("err", "lane"),  # a failed check, on the lanes of work
    ("err", "accent"),
    ("live", "lane"),
    ("err", "lane-lo"),  # a failed check among the shades of token use
    ("live", "accent"),
    ("mark", "sel-bg"),  # a search hit, where you are
    ("mark", "paper"),
    ("sel-bg", "paper"),
]
# The rail of a theme that gives it a surface of its own: its text and marks.
RAIL_TEXT = [
    ("ink", "paper"), ("ink-2", "paper"), ("ink", "sheet"), ("sel-ink", "sel-bg"),
    ("ink", "card"), ("card-ink-2", "card"),
]  # fmt: skip
RAIL_SHAPES = [("live", "paper")]


def block(selector: str) -> str:
    start = CSS.index(selector + " {")
    return CSS[start : CSS.index("}", start)]


def pairs(text: str) -> dict[str, tuple[str, str]]:
    found = re.findall(rf"--([a-z0-9-]+):\s*light-dark\(({HEX}),\s*({HEX})\)", text)
    return {name: (light, dark) for name, light, dark in found}


def palette(theme: str, mode: str, rail: bool = False) -> dict[str, str]:
    """The colours in force: the defaults, the theme's own, its rail's when asked."""
    found = pairs(block(":root"))
    if theme != THEMES[0][0]:
        found |= pairs(block(f':root[data-theme="{theme}"]'))
    if rail:
        found |= pairs(block(f':root[data-theme="{theme}"] .rail'))
    side = 0 if mode == "light" else 1
    return {name: both[side] for name, both in found.items()}


def has_rail(theme: str) -> bool:
    return f':root[data-theme="{theme}"] .rail {{' in CSS


def rgb(colour: str) -> tuple[float, float, float]:
    r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return r, g, b


def luminance(colour: str) -> float:
    def channel(s: float) -> float:
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def apart(a: str, b: str) -> bool:
    """Two colours that read as different things: different hues when both are colourful,
    colour against grey, or two greys of clearly different lightness."""
    chroma_a, chroma_b = (max(rgb(c)) - min(rgb(c)) for c in (a, b))
    if chroma_a >= 0.15 and chroma_b >= 0.15:
        hue_a, hue_b = (colorsys.rgb_to_hls(*rgb(c))[0] * 360 for c in (a, b))
        return min(abs(hue_a - hue_b), 360 - abs(hue_a - hue_b)) >= 30
    if (chroma_a >= 0.15) != (chroma_b >= 0.15):
        return True
    return contrast(a, b) >= 1.1


def on_page(theme: str, checks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The checks for the page; a rail with colours of its own is checked on its own."""
    return [c for c in checks if not (has_rail(theme) and "rail-bg" in c)]


CASES = [(theme, mode) for theme, _, _ in THEMES for mode in ("light", "dark")]
RAILS = [(theme, mode) for theme, mode in CASES if has_rail(theme)]


def test_every_theme_in_the_menu_has_its_colours() -> None:
    for theme, _, _ in THEMES[1:]:
        assert f':root[data-theme="{theme}"] {{' in CSS, theme


@pytest.mark.parametrize(("theme", "mode"), CASES)
def test_text_meets_wcag_aaa(theme: str, mode: str) -> None:
    colours = palette(theme, mode)
    low = {
        f"--{text} on --{ground}": round(contrast(colours[text], colours[ground]), 2)
        for text, ground in on_page(theme, TEXT)
        if contrast(colours[text], colours[ground]) < 7
    }
    assert not low, f"{theme} {mode}: {low}"


@pytest.mark.parametrize(("theme", "mode"), CASES)
def test_marks_that_are_not_text_stand_out(theme: str, mode: str) -> None:
    colours = palette(theme, mode)
    low = {
        f"--{mark} on --{ground}": round(contrast(colours[mark], colours[ground]), 2)
        for mark, ground in on_page(theme, SHAPES)
        if contrast(colours[mark], colours[ground]) < 3
    }
    assert not low, f"{theme} {mode}: {low}"


@pytest.mark.parametrize(("theme", "mode"), CASES)
def test_status_colours_keep_apart(theme: str, mode: str) -> None:
    colours = palette(theme, mode)
    alike = [f"--{a} / --{b}" for a, b in APART if not apart(colours[a], colours[b])]
    assert not alike, f"{theme} {mode}: these read as the same: {alike}"


@pytest.mark.parametrize(("theme", "mode"), RAILS)
def test_a_rail_of_its_own_is_legible(theme: str, mode: str) -> None:
    colours = palette(theme, mode, rail=True)
    low = [f"--{t} on --{g}" for t, g in RAIL_TEXT if contrast(colours[t], colours[g]) < 7]
    low += [f"--{m} on --{g}" for m, g in RAIL_SHAPES if contrast(colours[m], colours[g]) < 3]
    assert not low, f"{theme} {mode} rail: {low}"


@pytest.mark.parametrize(("theme", "mode"), CASES)
def test_the_shades_of_token_use_step_clearly(theme: str, mode: str) -> None:
    """One hue in three steps, high to low, each clearly lighter (or darker, on a dark
    page) than the one before it."""
    colours = palette(theme, mode)
    steps = [colours[name] for name in ("lane", "lane-mid", "lane-lo")]
    gaps = [round(contrast(a, b), 2) for a, b in pairwise(steps)]
    assert min(gaps) >= 1.5, f"{theme} {mode}: {gaps}"


@pytest.mark.parametrize(("theme", "mode"), CASES)
def test_the_card_for_the_session_you_are_reading_stands_off_its_rail(
    theme: str, mode: str
) -> None:
    """A shadow does not show on a dark rail, so the card's own surface has to."""
    colours = palette(theme, mode, rail=has_rail(theme))
    assert contrast(colours["card"], colours["rail-bg" if not has_rail(theme) else "paper"]) >= 1.15
