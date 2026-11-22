"""Proposing preferences and facts from sessions: a model reads the transcript and what
is already known, and returns candidates for the human to vet.

The model answers turn by turn: one entry for every human turn and answered
question, saying what it reveals (a preference, a decision, a fact, or nothing
lasting) and, when it reveals something, the full proposal. Walking every turn is
what a light model does reliably; collecting findings into a separate list
afterwards is where it lost most of them. Entries that repeat an earlier one point
to it (`same_as`) and are merged here, as more evidence for one proposal.

A second, smaller call edits that list (see `editor`): judging a short list against
"would this still matter to someone who has read the code?" is what the first pass,
busy reading, does badly. If the edit fails, the first pass's list is kept as it is.

Role: Extractor
    model: str
    extract(transcript, known, projects) -> Extracted
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from html import escape
from typing import Any, Protocol, runtime_checkable

from matters.errors import ModelError
from matters.knowledge import editor
from matters.knowledge.model import (
    CATEGORIES,
    CATEGORY_HELP,
    GLOBAL,
    KINDS,
    RELATIONS,
    Draft,
    Evidence,
    Item,
    Kind,
    Relation,
)
from matters.llm import Provider, Usage
from matters.redact import redact
from matters.transcript import Transcript

MAX_TOKENS = 48_000
MAX_KNOWN = 400  # accepted and rejected items shown to the model, newest first
REVEALS = ("preference", "decision", "fact", "nothing")

SYSTEM = f"""\
You read working sessions between a developer and an AI coding assistant, and propose the durable things a future assistant should know about this developer: their PREFERENCES (how they want things done) and FACTS (what is true about their projects, domains and environment). The developer vets every proposal in one click each; nothing is kept unless they accept it. Accepted items become PREFERENCES.md and FACTS.md, read by every future session.

# Where the knowledge is
Knowledge shows mostly in how the human reacts, not in what the assistant says. Read each <human> turn closely, with just enough of the assistant's preceding answer to know what they were reacting to. The signals, strongest first:
1. Explicit statements: "always", "never", "I prefer", "we use", "don't", "from now on", rules they lay down.
2. Corrections: "no, I meant…", "not like that", redoing or undoing what the assistant did. The correction implies the preference.
3. Choices: when the assistant offered options ("asked the human; they answered: ..."), what they picked and what they passed over, especially when they explained why or wrote their own answer.
4. Rejections and pushback: refusing a proposal, asking to remove something, "too much", "simpler".
5. Approval of a specific choice when an alternative was on the table: "perfect", "yes, that one".
6. Facts they assert or confirm: about the project, its users, the domain, constraints, their machine and accounts.
Do NOT infer from silence, and do not take the assistant's own claims or suggestions as knowledge unless the human clearly confirmed them.

# What is worth keeping
The test: would a future assistant that has ALREADY READ THE CODE still act differently for being told this? The code shows what was built; it does not show why, what was ruled out, what must stay true, or how the developer likes to work. Keep that:
- How they work with an assistant (look hardest for these; they are the most valuable and the easiest to miss): when to ask versus act, wanting options and their taste asked before building, wanting the usefulness of an idea argued before it is built, how much to explain, how long or plain answers and docs should be, what to verify before calling something done. Usually global.
- Taste: visual style, wording, code style, tech they reach for or avoid. Global unless tied to one project.
- Constraints and principles behind a project's features: "on demand, never by default", "everything stays local and read-only", "free-tier models only", "only inline blocks, files are in git already". Project-scoped.
- Directions ruled out, and choices between options where the alternative could come back ("export on demand, not written into CLAUDE.md").
- Facts about a project, domain or environment that the code does not show ("the free Gemini key cannot use 2.5 models").
Nothing lasting:
- what was built: a feature request restated ("add a stop command", "implement a timeline view") is in the code now. Keep only the constraint or taste behind it, if there is one;
- actions and one-offs ("restart it", "go on", "run it again", a bug report once fixed);
- what is true only for that moment (the current error, a temporary workaround);
- generic best practice any competent assistant follows anyway ("write tests");
- secrets, keys, tokens, passwords, email addresses, personal details about people;
- the assistant's own reasoning, guesses and plans.
When it passes the test but you are unsure it will hold, propose it: rejecting costs one click.

# How to answer: turn by turn
Walk the sessions in order. For EVERY <human> turn and EVERY answered question write at least one entry in "turns"; do not skip any. One entry per distinct thing the turn reveals (a question answered with four choices can reveal four decisions). A turn that reveals nothing lasting gets exactly one entry with reveals "nothing" and empty strings elsewhere.
For each entry:
- session, turn: where it is (session id like "S1", turn number as shown).
- reveals: "preference", "decision", "fact" or "nothing".
- kind: "preference" for preferences and for decisions that guide future work; "fact" for facts and for decisions that describe how the project is.
- category, one of:
{chr(10).join(f"  - {name}: {CATEGORY_HELP[name]}" for name in CATEGORIES)}
- scope: "global" (their taste and way of working, in any project) or "project" (tied to this project or its domain; most decisions and facts). When unsure, "project".
- statement: one sentence, at most 25 words, written for a future assistant. Preferences and decisions as instructions ("Prefer X over Y", "Ask before Z", "Keep artifacts to inline blocks from answers"); facts as plain statements. Specific: name the tool, the pattern, the word. No hedging, no "the user".
- why: ONLY if the human gave a reason in their own words (because, so that, since, otherwise, "as ..."): that reason as a short clause, at most 15 words. If they gave none, an empty string. Never supply a reason yourself.
- basis: "stated" if they said it outright; "reaction" if it follows from a correction, choice, rejection or approval.
- quote: a short verbatim quote (at most 200 characters) of the HUMAN's words in THIS turn that show it. Never quote the assistant.
- same_as: if this entry says the same as an EARLIER entry in your answer, that entry's place as "S1:10"; otherwise "". Write the statement anyway; the two are merged.
- relation and existing: against the developer's ACCEPTED items (listed with ids): "duplicate" (says the same; existing = its id), "updates" (refines or changes it; existing = its id; write the full new statement), "contradicts" (conflicts with it; existing = its id), or "new" (existing = 0).
Never propose again what the developer REJECTED, even reworded, unless the session gives clearly new and stronger evidence.
Never propose what their instruction files (<already_written>) already say, even reworded: those rules are known. Propose only what adds to them, or what a session shows has changed (then say so in the statement).

Answer with JSON only, following the schema.
"""

USER_TEMPLATE = """\
{known}
{written}

Sessions to read ({count}), oldest first. Turns are numbered per session.
{notes}
{transcript}

Now answer turn by turn, as JSON."""

_ENTRY_FIELDS: dict[str, Any] = {
    "session": {"type": "string", "description": "e.g. S1"},
    "turn": {"type": "integer"},
    "reveals": {"type": "string", "enum": list(REVEALS)},
    "kind": {"type": "string", "enum": [*KINDS, ""]},
    "category": {"type": "string", "enum": [*CATEGORIES, ""]},
    "scope": {"type": "string", "enum": ["global", "project", ""]},
    "statement": {"type": "string"},
    "why": {"type": "string"},
    "basis": {"type": "string", "enum": ["stated", "reaction", ""]},
    "quote": {"type": "string"},
    "same_as": {"type": "string", "description": 'an earlier entry, e.g. "S1:10", or ""'},
    "relation": {"type": "string", "enum": list(RELATIONS)},
    "existing": {"type": "integer", "description": "accepted item id, or 0"},
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["turns"],
    "properties": {
        "turns": {
            "type": "array",
            "description": "At least one entry per human turn and answered question, in order.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(_ENTRY_FIELDS),
                "properties": _ENTRY_FIELDS,
            },
        }
    },
}
_PLACE = re.compile(r"^\s*(S\d+)\s*[:#/ ]\s*t?(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Extracted:
    drafts: tuple[Draft, ...]
    usage: Usage
    dropped: int = 0  # entries that revealed something but lacked usable fields or evidence
    turns_read: int = 0  # entries the model wrote, "nothing" included

    @classmethod
    def from_model_output(
        cls,
        data: dict[str, Any],
        transcript: Transcript,
        known: Sequence[Item],
        projects: Mapping[str, str],
        usage: Usage,
    ) -> "Extracted":
        """Turn entries into proposals: keep what is well-formed and cited, repair what can
        be repaired, merge repeats into the entry they repeat, drop the rest."""
        raw = data.get("turns")
        if not isinstance(raw, list):
            raise ModelError("The model's answer had no list of turns.")
        accepted = _accepted_ids(known)
        drafts: list[Draft] = []
        first_at: dict[tuple[str, int], int] = {}  # (alias, turn) -> index of its first draft
        dropped = 0
        for entry in map(ModelEntry, (e for e in raw if isinstance(e, dict))):
            if not entry.reveals_something:
                continue
            if (draft := entry.to_draft(transcript, accepted, projects)) is None:
                dropped += 1
            elif (repeats := entry.same_as) in first_at:
                index = first_at[repeats]
                drafts[index] = drafts[index].merged_with(draft)
            else:
                first_at.setdefault(entry.place, len(drafts))
                drafts.append(draft)
        return cls(tuple(drafts), usage, dropped, len(raw))

    def edited_by(
        self,
        data: dict[str, Any],
        transcript: Transcript,
        known: Sequence[Item],
        projects: Mapping[str, str],
    ) -> tuple[Draft, ...]:
        """The editor's verdicts applied; its additions held to the same citation rules as
        the first pass. An answer without verdicts leaves the list as it was."""
        if not isinstance(data.get("verdicts"), list):
            return self.drafts
        accepted = _accepted_ids(known)
        additions = (ModelEntry.addition(e) for e in data.get("added", []) if isinstance(e, dict))
        added = [d for e in additions if (d := e.to_draft(transcript, accepted, projects))]
        return tuple(editor.apply(data, self.drafts, added, projects))


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """One entry the model wrote for a turn, as raw JSON."""

    data: dict[str, Any]

    @classmethod
    def addition(cls, added: dict[str, Any]) -> "ModelEntry":
        """Something the editor added, in the first pass's shape."""
        reveals = "fact" if added.get("kind") == "fact" else "preference"
        return cls({**added, "reveals": reveals, "relation": "new", "existing": None})

    @property
    def reveals_something(self) -> bool:
        return self.data.get("reveals") in REVEALS[:3]

    @property
    def place(self) -> tuple[str, int]:
        """(session alias, turn), as the model wrote them."""
        return str(self.data.get("session", "")).strip().upper(), int(self.data.get("turn", 0))

    @property
    def same_as(self) -> tuple[str, int] | None:
        """The place of an earlier entry this one repeats."""
        match = _PLACE.match(str(self.data.get("same_as") or ""))
        return (match.group(1).upper(), int(match.group(2))) if match else None

    def evidence(self, transcript: Transcript) -> Evidence | None:
        """The turn it cites, if that turn exists in the transcript."""
        session_id = transcript.aliases.get(str(self.data.get("session", "")).strip().upper())
        turn = self.data.get("turn")
        if session_id is None or not isinstance(turn, int):
            return None
        if not 1 <= turn <= transcript.turns.get(session_id, 0):
            return None
        quote = redact(" ".join(str(self.data.get("quote", "")).split()))[:300]
        return Evidence(session_id, turn, quote)

    def to_draft(
        self, transcript: Transcript, accepted_ids: set[int], projects: Mapping[str, str]
    ) -> Draft | None:
        """A proposal, or None when it says nothing or cites nothing that can be checked."""
        entry = self.data
        statement = " ".join(str(entry.get("statement", "")).split())
        evidence = self.evidence(transcript)
        if not statement or evidence is None:
            return None  # traceability: nothing is proposed that cannot be checked
        reveals = entry.get("reveals")
        fallback: Kind = "fact" if reveals == "fact" else "preference"
        kind: Kind = next((k for k in KINDS if k == entry.get("kind")), fallback)
        existing = entry.get("existing")
        related = existing if isinstance(existing, int) and existing in accepted_ids else None
        relation: Relation = next(
            (r for r in RELATIONS if r == entry.get("relation") and related is not None), "new"
        )
        project_scoped = entry.get("scope") != "global" or reveals == "decision"
        category = entry.get("category")
        return Draft(
            kind=kind,
            scope=projects.get(evidence.session_id, GLOBAL) if project_scoped else GLOBAL,
            category=category if category in CATEGORIES else "workflow",
            statement=redact(statement),
            why=redact(" ".join(str(entry.get("why", "")).split())),
            basis="stated" if entry.get("basis") == "stated" else "reaction",
            evidence=(evidence,),
            relation=relation,
            related_id=related,
        )


@runtime_checkable
class Extractor(Protocol):
    """Role: propose knowledge from a transcript, given what is already known."""

    @property
    def model(self) -> str: ...

    def extract(
        self, transcript: Transcript, known: Sequence[Item], projects: Mapping[str, str]
    ) -> Extracted: ...


class LlmExtractor:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    @property
    def model(self) -> str:
        return self.provider.model

    def extract(
        self, transcript: Transcript, known: Sequence[Item], projects: Mapping[str, str]
    ) -> Extracted:
        user = user_message(transcript, known)
        read = self.provider.complete_json(SYSTEM, user, SCHEMA, max_tokens=MAX_TOKENS)
        first = Extracted.from_model_output(read.data, transcript, known, projects, read.usage)
        if not first.drafts:
            return first
        try:
            edit = editor.ask(self.provider, first.drafts, transcript)
        except ModelError:
            return first  # the read is paid for; an unedited list beats none
        drafts = first.edited_by(edit.data, transcript, known, projects)
        return replace(first, usage=first.usage + edit.usage, drafts=drafts)


def user_message(transcript: Transcript, known: Sequence[Item]) -> str:
    notes = "\n".join(f"Note: {n}" for n in transcript.clipped)
    written = (
        f"<already_written>\n{transcript.written}\n</already_written>\n"
        if transcript.written
        else ""
    )
    return USER_TEMPLATE.format(
        known=_known(known),
        written=written,
        count=len(transcript.aliases),
        notes=notes,
        transcript=transcript.text,
    )


def _accepted_ids(known: Sequence[Item]) -> set[int]:
    return {i.id for i in known if i.status == "accepted"}


def _known(known: Sequence[Item]) -> str:
    accepted = [i for i in known if i.status == "accepted"][:MAX_KNOWN]
    rejected = [i for i in known if i.status == "rejected"][:MAX_KNOWN]

    def line(item: Item, with_id: bool) -> str:
        ident = f' id="{item.id}"' if with_id else ""
        return (
            f'<item{ident} kind="{item.kind}" category="{escape(item.category)}">'
            f"{escape(redact(item.statement), quote=False)}</item>"
        )

    return (
        "<accepted>\n" + "\n".join(line(i, True) for i in accepted) + "\n</accepted>\n"
        "<rejected>\n" + "\n".join(line(i, False) for i in rejected) + "\n</rejected>"
    )
