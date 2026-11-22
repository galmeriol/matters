"""The second pass of extraction: an editor that judges the candidates.

The first pass walks every turn and proposes generously; a light model does that
well, but it cannot also hold the line on what is worth keeping. Judging a short
list is easier: for each candidate, would an assistant that has already read the
code still act differently for being told it? The editor keeps those, rewritten
down to the durable part (the rule, not the feature), merges repeats, and adds
what the first pass missed about how the developer works, from their own words.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from html import escape
from typing import Any

from matters.knowledge.model import CATEGORIES, GLOBAL, KINDS, Draft
from matters.llm import Completion, Provider
from matters.redact import redact
from matters.transcript import Transcript

MAX_TOKENS = 32_000
HUMAN_CLIP = 700  # characters of the human's words per turn

SYSTEM = """\
You are the editor of a developer's PREFERENCES.md and FACTS.md. A first pass read their sessions with an AI coding assistant and proposed candidates, generously. You decide which are worth the developer's attention, and make each one sharp.

# The test
Would a future assistant that has ALREADY READ THE PROJECT'S CODE still act differently for being told this? The code shows what was built. It does not show why, what must stay true, what was ruled out, or how the developer likes to work.

What lasts:
- How they work with an assistant: asking about options and taste before building, wanting the usefulness of an idea argued before it is built, how much to explain, how plain or short answers and docs should be, what to verify before calling something done.
- Taste: visual style, wording, code style, tech they reach for or avoid.
- Constraints and principles behind features: "on demand, never by default", "local and read-only", "free-tier models", "only inline blocks; files are in git".
- Directions ruled out, and choices where the alternative could come back.
- Facts the code does not show: about the domain, the environment, accounts, limits.

What does not last:
- A feature request as such ("Add a stop command", "Implement a timeline view", "Render Markdown"): the code shows it now. But most requests carry a constraint or a taste in HOW they are asked; that part lasts. "Add export, on demand only" carries "Make features opt-in, never on by default". "Write a short README with minimal steps" carries "Keep docs minimal: a short intro and the fewest steps". "Let's think about why this is useful first" carries "Argue an idea's usefulness before building it".
- One-offs, actions, bug reports, things true only for that moment.
- Generic best practice any competent assistant follows anyway.
- Vague statements with nothing to act on ("Use a modern Python setup").

# For each candidate
Write one verdict with its index i:
- rule: first ask what lasts in it, then write only that part, as one sentence of at most 25 words for a future assistant: an instruction for preferences ("Ask about options and taste before building a feature with real choices"), a plain statement for facts. Specific, never the feature itself. "" if nothing lasts.
- merge_into: if its rule is the same as an earlier candidate's rule, that candidate's index; otherwise -1.
- kind, category, scope: for the rule, corrected if needed. scope "global" for taste and ways of working that hold in any project; "project" for constraints, decisions and facts tied to one project.
- why: the reason the developer gave in their own words, as a short clause, if there is one; otherwise "". Never supply a reason yourself.

# Then add what was missed
Read the developer's own words (below, turn by turn) once more, only for how they work with an assistant and for their taste. Look for: questions they push back with ("why would this be useful?"), invitations ("ask me if…"), words that set a bar ("minimal", "proper", "classy", "plain", "highest legibility"), words that limit ("not by default", "only", "never", "for now"), and the same kind of request made in several turns. Add each one no rule above already covers, citing the turn where it shows most clearly, with a short verbatim quote of the developer's words. Most sessions have a few; add none only if there truly are none.

Answer with JSON only, following the schema.
"""

USER_TEMPLATE = """\
<candidates>
{candidates}
</candidates>

The developer's own words, turn by turn:
<human_words>
{words}
</human_words>

Now write a verdict for every candidate, then the items that were missed, as JSON."""

_KIND = {"type": "string", "enum": list(KINDS)}
_CATEGORY = {"type": "string", "enum": list(CATEGORIES)}
_SCOPE = {"type": "string", "enum": ["global", "project"]}
_VERDICT: dict[str, Any] = {  # in this order: the rule is written before anything is decided
    "i": {"type": "integer"},
    "rule": {"type": "string"},
    "merge_into": {"type": "integer"},
    "kind": _KIND,
    "category": _CATEGORY,
    "scope": _SCOPE,
    "why": {"type": "string"},
}
_ADDED: dict[str, Any] = {
    "session": {"type": "string"},
    "turn": {"type": "integer"},
    "quote": {"type": "string"},
    "statement": {"type": "string"},
    "kind": _KIND,
    "category": _CATEGORY,
    "scope": _SCOPE,
    "why": {"type": "string"},
    "basis": {"type": "string", "enum": ["stated", "reaction"]},
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts", "added"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(_VERDICT),
                "properties": _VERDICT,
            },
        },
        "added": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(_ADDED),
                "properties": _ADDED,
            },
        },
    },
}

_SESSION = re.compile(r'<session id="(S\d+)"[^>]*>(.*?)</session>', re.DOTALL)
_TURN = re.compile(r'<turn n="(\d+)">(.*?)</turn>', re.DOTALL)
_HUMAN = re.compile(r"<human>(.*?)</human>", re.DOTALL)
_ANSWERED = re.compile(r"asked the human; they answered: (.*)")


def ask(provider: Provider, drafts: Sequence[Draft], transcript: Transcript) -> Completion:
    aliases = {sid: alias for alias, sid in transcript.aliases.items()}
    user = USER_TEMPLATE.format(
        candidates="\n".join(_candidate(i, d, aliases) for i, d in enumerate(drafts)),
        words=human_words(transcript),
    )
    return provider.complete_json(SYSTEM, user, SCHEMA, max_tokens=MAX_TOKENS)


def _candidate(index: int, draft: Draft, aliases: Mapping[str, str]) -> str:
    quotes = "".join(
        f'<quote at="{aliases.get(e.session_id, "?")}:{e.turn}">{escape(e.quote, quote=False)}</quote>'
        for e in draft.evidence
    )
    why = f"<why>{escape(draft.why, quote=False)}</why>" if draft.why else ""
    scope = "global" if draft.scope == GLOBAL else "project"
    return (
        f'<c i="{index}" kind="{draft.kind}" category="{draft.category}" scope="{scope}" '
        f'basis="{draft.basis}">{escape(draft.statement, quote=False)}{quotes}{why}</c>'
    )


def human_words(transcript: Transcript) -> str:
    """Only what the developer said and chose, per turn: the editor's evidence."""
    lines = []
    for alias, body in _SESSION.findall(transcript.text):
        for number, turn in _TURN.findall(body):
            said = " ".join(" ".join(_HUMAN.findall(turn)).split())
            chose = " ".join(a.strip() for a in _ANSWERED.findall(turn))
            words = " ".join(w for w in (said, f"[chose: {chose}]" if chose else "") if w)
            if words:
                clipped = words if len(words) <= HUMAN_CLIP else words[:HUMAN_CLIP] + " […]"
                lines.append(f'<turn at="{alias}:{number}">{clipped}</turn>')
    return "\n".join(lines)


def apply(
    data: dict[str, Any],
    drafts: Sequence[Draft],
    added: Sequence[Draft],
    projects: Mapping[str, str],
) -> list[Draft]:
    """The candidates the editor kept (rewritten, with merged evidence), then its additions.
    A candidate the editor gave no verdict keeps its place unchanged."""
    verdicts = {
        v["i"]: v
        for v in data.get("verdicts", [])
        if isinstance(v, dict) and isinstance(v.get("i"), int) and 0 <= v["i"] < len(drafts)
    }
    kept: dict[int, Draft] = {}
    for index, draft in enumerate(drafts):
        verdict = verdicts.get(index)
        target = verdict.get("merge_into") if verdict else None
        if verdict is None:
            kept[index] = draft
        elif isinstance(target, int) and target in kept:
            kept[target] = kept[target].with_evidence_of(draft)
        elif _rule(verdict):
            kept[index] = _rewritten(draft, verdict, projects)
    return [*kept.values(), *added]


def _rule(verdict: dict[str, Any]) -> str:
    return redact(" ".join(str(verdict.get("rule", "")).split()))


def _rewritten(draft: Draft, verdict: dict[str, Any], projects: Mapping[str, str]) -> Draft:
    statement = _rule(verdict)
    scope = (
        GLOBAL
        if verdict.get("scope") == "global"
        else projects.get(draft.evidence[0].session_id, draft.scope)
    )
    why = redact(" ".join(str(verdict.get("why", "")).split()))
    return replace(
        draft,
        statement=statement,
        kind=verdict["kind"] if verdict.get("kind") in KINDS else draft.kind,
        category=verdict["category"] if verdict.get("category") in CATEGORIES else draft.category,
        scope=scope,
        why=why if draft.why else "",  # a reason only where the first pass found one
    )
