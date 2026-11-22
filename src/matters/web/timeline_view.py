"""The session timeline: one lane per activity, from the record alone, on one axis of active
time. Ink blocks on paper; each block links to the turn it starts in. The lane is the
category, so no colour is needed.

It sits folded under its one-line summary, so the conversation stays the first thing on
the page; the lanes are one click (or `t`) away, and stay open once opened.

Token use rides along: each block's hover card shows what its model calls consumed, and
small three-bar meters (lane totals, the turn index) say high / medium / low relative to
the rest of the session, so you can see where the tokens went before opening anything.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from typing import Literal

from matters.session import Session, Tokens
from matters.timeline import ACTIVITIES, Segment, Timeline
from matters.web.text import count, duration, short_duration

ACTIVITY_HELP = {
    "you": "reading answers and writing asks",
    "discuss": "the assistant explaining, planning, answering",
    "explore": "reading code and docs, searching",
    "build": "editing files, installing",
    "verify": "tests, linters, type checks, smoke tests",
    "debug": "work between a failed check and the next passing one",
    "run": "serving, stopping, version control",
}
MIN_WIDTH = 0.25  # percent: even a one-second step stays visible
# Shading the marks by their token use, for the cost under the time; the page script shows
# it and keeps your choice. Plain is the default: the chart is about time.
SHADE = (
    '<div class="tl-shade" hidden><span class="tl-shade-label">Shade marks</span>'
    '<span class="switch"><button type="button" data-shade="">Plain</button>'
    '<button type="button" data-shade="tokens">By token use</button></span>'
    '<span class="tl-key"><i class="lv-high"></i>more tokens <i class="lv-low"></i>fewer '
    '<i class="lv-none"></i>none <span class="quiet">· compared within this session</span>'
    "</span></div>"
)

type Level = Literal["none", "low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class TimelineView:
    section: str  # the timeline, above the turns
    turn_meters: dict[int, str]  # turn -> meter HTML, for the turn index
    turn_seconds: dict[int, float]  # turn -> the assistant's active seconds
    line: Timeline | None = None  # the figures the page's header quotes


@dataclass(frozen=True, slots=True)
class _Block:
    start: float
    seconds: float
    turn: int
    tip: str
    failed: bool = False
    tokens: Level = "none"  # its token use against the session's other marks


def level(weight: float, average: float) -> Level:
    """Relative to the session: over twice the average is high, under half is low."""
    if weight <= 0 or average <= 0:
        return "none"
    ratio = weight / average
    return "high" if ratio >= 2 else "low" if ratio < 0.5 else "medium"


def _average(weights: Iterable[float]) -> float:
    used = [w for w in weights if w > 0]
    return sum(used) / len(used) if used else 0.0


def meter(lvl: Level, tip: str) -> str:
    """Three bars, filled by level; the hover card says what they measure."""
    if lvl == "none":
        return ""
    return (
        f'<span class="meter lv-{lvl}" tabindex="0" role="img" aria-label="{lvl} token use" '
        f'data-tip="{escape(tip)}"><i></i><i></i><i></i></span>'
    )


def tokens_text(tokens: Tokens) -> str:
    if not tokens.total:
        return "no model calls"
    return (
        f"{count(tokens.total)} tokens: {count(tokens.output)} out, "
        f"{count(tokens.input + tokens.cache_write)} new in, {count(tokens.cache_read)} cached"
    )


def timeline_view(session: Session) -> TimelineView:
    line = Timeline.of(session)
    total = line.active_seconds
    turn_tokens = line.turn_tokens
    turn_average = _average(t.weight for t in turn_tokens.values())
    turn_meters = {
        turn: meter(
            level(tokens.weight, turn_average),
            f"turn {turn}: {level(tokens.weight, turn_average)} token use\n{tokens_text(tokens)}",
        )
        for turn, tokens in turn_tokens.items()
    }
    turn_seconds = {turn: end - start for turn, (start, end) in line.turn_spans.items()}
    if total <= 0:
        return TimelineView("", turn_meters, turn_seconds, line)
    block_average = _average(s.tokens.weight for s in line.segments)
    lane_average = _average(line.tokens_in(a).weight for a in ACTIVITIES)
    activity = "".join(
        _lane(
            name,
            ACTIVITY_HELP[name],
            (
                _Block(
                    s.start,
                    s.seconds,
                    s.turn,
                    _activity_tip(s, block_average),
                    s.failed > 0,
                    level(s.tokens.weight, block_average),
                )
                for s in line.segments
                if s.activity == name
            ),
            line.seconds_in(name),
            total,
            line.tokens_in(name),
            lane_average,
        )
        for name in ACTIVITIES
    )
    kinds = sum(1 for a in ACTIVITIES if line.seconds_in(a) > 0)
    away = (
        f" ({duration(line.away_seconds)} when nobody was working is cut out, at the dotted ticks)"
        if line.away_seconds >= 60
        else ""
    )
    return TimelineView(
        f"""<details class="timeline" id="timeline" open>
  <summary class="tl-summary"><span class="label">Where the time went</span>
    <span class="tl-lede">{kinds} kinds of work over {duration(total)} of active time</span></summary>
  <p class="tl-how">Each row is one kind of work across the active time{away}. A mark is a stretch of it:
    wider took longer, <span class="err">red</span> had a failed check. Point at a name or a mark for details; click a mark to open its turn.
    <span class="tl-zoom-hint" hidden>Drag across the lanes to zoom in, pinch or ⌘-scroll to zoom, scroll sideways to pan, double-click to zoom out.</span></p>
  {SHADE}
  <div class="tl-grid" aria-label="Activity over active time" data-total="{total:.3f}">
    <span></span><span class="tl-col tl-range">over the session →</span><span class="tl-col pct">share</span><span class="tl-col tl-time">time</span><span class="tl-col tl-meter" data-tip="Token use, low / medium / high against the other rows" tabindex="0">tokens</span>
    {activity}
    {_axis(line)}
  </div>
</details>""",
        turn_meters,
        turn_seconds,
        line,
    )


def _activity_tip(segment: Segment, average: float) -> str:
    steps = f"{segment.steps} step{'s' if segment.steps != 1 else ''}"
    fails = f", {segment.failed} failed" if segment.failed else ""
    lines = [
        f"{segment.activity} · {duration(segment.seconds)} · {steps}{fails} · turn {segment.turn}",
        tokens_text(segment.tokens),
    ]
    lvl = level(segment.tokens.weight, average)
    if lvl != "none":
        lines.append(f"token use: {lvl} for this session")
    return "\n".join(lines)


def _lane(
    name: str,
    help_text: str,
    blocks: Iterable[_Block],
    seconds: float,
    total: float,
    tokens: Tokens,
    average: float,
) -> str:
    drawn = "".join(_block(b, total) for b in blocks if b.turn)
    share = seconds / total * 100 if total else 0
    empty = " empty" if seconds <= 0 and not tokens.total else ""
    lvl = level(tokens.weight, average)
    gauge = meter(lvl, f"{name}: {lvl} token use\n{tokens_text(tokens)}")
    return f"""<span class="tl-name{empty}" tabindex="0" data-tip="{escape(name)}: {escape(help_text)}">{escape(name)}</span>
<div class="tl-lane{empty}">{drawn}</div>
<span class="tl-total{empty}"><span class="pct">{share:.0f}%</span><span class="tl-time">{short_duration(seconds)}</span><span class="tl-meter">{gauge}</span></span>"""


def _block(block: _Block, total: float) -> str:
    left = block.start / total * 100
    width = max(block.seconds / total * 100, MIN_WIDTH)
    edge = " tip-start" if left < 12 else " tip-end" if left + width > 88 else ""
    return (
        f'<a class="tl-seg{" failed" if block.failed else ""}{edge}" href="#t{block.turn}" draggable="false" '
        f'data-start="{block.start:.3f}" data-seconds="{block.seconds:.3f}" data-tokens="{block.tokens}" '
        f'data-tip="{escape(block.tip)}" aria-label="{escape(block.tip.splitlines()[0])}" '
        f'style="left:{left:.3f}%;width:{width:.3f}%"></a>'
    )


def _axis(line: Timeline) -> str:
    total = line.active_seconds
    ticks = "".join(
        f'<span class="tl-tick" style="left:{share}%">{short_duration(total * share / 100)}</span>'
        for share in (0, 25, 50, 75, 100)
    )
    breaks = "".join(
        f'<span class="tl-away" data-at="{at:.3f}" style="left:{at / total * 100:.3f}%" title="away {duration(seconds)}"></span>'
        for at, seconds in line.away
        if seconds >= 60
    )
    return f'<div class="tl-axis" aria-hidden="true">{ticks}{breaks}</div>'
