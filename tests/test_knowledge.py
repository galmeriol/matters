"""Knowledge: what extraction proposes, how it is stored and vetted, what is exported."""

import io
from pathlib import Path
from typing import Any

import pytest

from matters.errors import ModelError
from matters.jobs import Jobs
from matters.knowledge import editor
from matters.knowledge.export import markdown
from matters.knowledge.extractor import (
    SCHEMA,
    SYSTEM,
    Extracted,
    LlmExtractor,
    user_message,
)
from matters.knowledge.model import GLOBAL, Draft, Evidence, Item
from matters.knowledge.store import Added, KnowledgeStore
from matters.llm import Usage
from matters.session import Entry, Session, SourceRef, ToolCall
from matters.transcript import Transcript
from matters.web.app import Viewer
from matters.workbench import Workbench
from tests.fakes import FakeProvider, FakeSource

REF = SourceRef(Path("x.jsonl"), 1)
USAGE = Usage("fake-model", 10, 5)
SECRET = "sk-ant-" + "a1b2c3d4e5f6g7h8i9"


def session(sid: str = "s1", project: str = "/w/shop") -> Session:
    question = ToolCall(
        "AskUserQuestion",
        {"questions": []},
        'The user answered: "Which store?"="SQLite (Recommended)"',
    )
    entries = (
        Entry("ask", "add caching to the api", REF),
        Entry("text", "I'll use an ABC for the cache backend.", REF),
        Entry("ask", "no, we use typing.Protocol for roles, never ABCs", REF),
        Entry("tool", "", REF, question),
        Entry("text", "Done with SQLite.", REF),
    )
    return Session(sid, "claude-code", Path(project), entries, title="Caching")


def item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "preference",
        "category": "architecture",
        "scope": "global",
        "statement": "Use typing.Protocol for roles, never ABCs",
        "why": "",
        "basis": "reaction",
        "session": "S1",
        "turn": 2,
        "quote": "no, we use typing.Protocol",
        "reveals": "preference",
        "same_as": "",
        "relation": "new",
        "existing": 0,
    }
    return base | overrides


def parse(items: list[dict[str, Any]], known: list[Item] | None = None) -> tuple[Draft, ...]:
    text = Transcript.build([session()])
    extracted = Extracted.from_model_output(
        {"turns": items}, text, known or [], {"s1": "/w/shop"}, USAGE
    )
    return extracted.drafts


# What the model sees and proposes


def test_the_transcript_carries_the_humans_answers_to_questions() -> None:
    text = Transcript.build([session()]).text
    assert 'they answered: The user answered: "Which store?"="SQLite (Recommended)"' in text


def test_the_prompt_lists_accepted_items_with_ids_and_rejected_ones_without() -> None:
    known = [
        Item(
            7,
            "preference",
            GLOBAL,
            "tech",
            "Prefer uv",
            "",
            "stated",
            (),
            "accepted",
            "new",
            None,
            "m",
            "",
        ),
        Item(
            9,
            "fact",
            GLOBAL,
            "tech",
            "Uses Poetry",
            "",
            "stated",
            (),
            "rejected",
            "new",
            None,
            "m",
            "",
        ),
    ]
    message = user_message(Transcript.build([session()]), known)
    assert '<item id="7" kind="preference" category="tech">Prefer uv</item>' in message
    assert '<item kind="fact" category="tech">Uses Poetry</item>' in message
    assert "Do NOT infer from silence" in SYSTEM
    assert SCHEMA["properties"]["turns"]["items"]["additionalProperties"] is False


def test_proposals_are_kept_only_with_evidence_from_a_real_turn() -> None:
    drafts = parse(
        [
            item(),
            item(statement="No turn", turn=None),
            item(statement="Unknown session", session="S9", turn=1),
            item(statement="Turn out of range", turn=99),
            item(statement="", turn=1),
            item(statement="Nothing lasting", reveals="nothing", turn=3),
        ]
    )
    assert [d.statement for d in drafts] == ["Use typing.Protocol for roles, never ABCs"]
    assert drafts[0].evidence == (Evidence("s1", 2, "no, we use typing.Protocol"),)


def test_project_scope_is_the_project_of_the_cited_session() -> None:
    (draft,) = parse([item(scope="project", kind="fact", statement="Shop runs on SQLite")])
    assert draft.scope == "/w/shop" and draft.kind == "fact"


def test_unknown_categories_relations_and_ids_are_repaired() -> None:
    (draft,) = parse([item(category="vibes", relation="updates", existing=42)])
    assert draft.category == "workflow"
    assert draft.relation == "new" and draft.related_id is None  # 42 is not an accepted id


def test_secrets_never_reach_a_proposal() -> None:
    (draft,) = parse([item(statement=f"Use key {SECRET}", why=f"it is {SECRET}")])
    assert SECRET not in draft.statement and SECRET not in draft.why


def test_an_answer_without_turns_is_an_error() -> None:
    text = Transcript.build([session()])
    with pytest.raises(ModelError):
        Extracted.from_model_output({"oops": 1}, text, [], {}, USAGE)


# The editor: a second call that judges the first pass's list


def verdict(i: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "i": i,
        "rule": "",
        "merge_into": -1,
        "kind": "preference",
        "category": "architecture",
        "scope": "global",
        "why": "",
    }
    return base | overrides


def extract(first: dict[str, Any], *then: dict[str, Any] | ModelError) -> Extracted:
    provider = FakeProvider(first, then=then)
    extracted = LlmExtractor(provider).extract(Transcript.build([session()]), [], {"s1": "/w/shop"})
    assert len(provider.requests) == 1 + len(then)
    return extracted


FIRST = {
    "turns": [
        item(),
        item(statement="Add caching to the api", turn=1, quote="add caching to the api"),
        item(statement="Roles are Protocols", turn=2, quote="never ABCs"),
    ]
}


def test_the_editor_sees_candidates_and_only_the_humans_words() -> None:
    provider = FakeProvider(FIRST)
    LlmExtractor(provider).extract(Transcript.build([session()]), [], {"s1": "/w/shop"})
    system, user, schema = provider.requests[1]
    assert system == editor.SYSTEM and schema == editor.SCHEMA
    assert '<c i="1" kind="preference"' in user and "Add caching to the api" in user
    assert '<turn at="S1:2">no, we use typing.Protocol for roles, never ABCs [chose: ' in user
    assert "[chose: " in user and "SQLite (Recommended)" in user
    assert "I'll use an ABC" not in user.split("<human_words>")[1]  # the assistant's words stay out


def test_the_editor_drops_rewrites_merges_and_adds() -> None:
    edit = {
        "verdicts": [
            verdict(0, rule="Model roles as typing.Protocol, never ABCs"),
            verdict(1),
            verdict(2, rule="Roles are Protocols", merge_into=0),
        ],
        "added": [
            {
                "session": "S1",
                "turn": 1,
                "quote": "add caching",
                "statement": "Shop caches its api",
                "kind": "fact",
                "category": "tech",
                "scope": "project",
                "why": "",
                "basis": "stated",
            },
            {"session": "S9", "turn": 1, "quote": "x", "statement": "Uncited", "kind": "fact"},
        ],
    }
    extracted = extract(FIRST, edit)
    kept, added = extracted.drafts
    assert kept.statement == "Model roles as typing.Protocol, never ABCs"
    assert len(kept.evidence) == 1  # the merged candidate cited the same turn
    assert (added.statement, added.kind, added.scope) == ("Shop caches its api", "fact", "/w/shop")
    assert extracted.usage == Usage("fake-model", 20, 10)  # both calls are counted


def test_the_editor_never_invents_a_reason_or_hides_a_secret() -> None:
    edit = {"verdicts": [verdict(0, rule=f"Use {SECRET}", why="because it is faster")]}
    (first, *_) = extract({"turns": [item()]}, edit).drafts
    assert SECRET not in first.statement
    assert first.why == ""  # the first pass found no reason, so none is supplied


def test_without_a_usable_edit_the_first_pass_stands() -> None:
    failed = ModelError("busy")
    for edit in ({"oops": 1}, failed):
        drafts = extract(FIRST, edit).drafts
        assert [d.statement for d in drafts] == [
            "Use typing.Protocol for roles, never ABCs",
            "Add caching to the api",
            "Roles are Protocols",
        ]


def test_candidates_without_a_verdict_are_kept() -> None:
    drafts = extract(FIRST, {"verdicts": [verdict(1)], "added": []}).drafts
    assert len(drafts) == 2


# The store


def draft(statement: str, **overrides: Any) -> Draft:
    base: dict[str, Any] = {
        "kind": "preference",
        "scope": GLOBAL,
        "category": "architecture",
        "statement": statement,
        "why": "",
        "basis": "stated",
        "evidence": (Evidence("s1", 1, "quote"),),
    }
    return Draft(**(base | overrides))


def test_repeats_add_evidence_and_rejected_items_never_come_back(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "m.db")
    assert len(store.add([draft("Prefer uv"), draft("Use Poetry")], "m").new) == 2
    poetry = next(i for i in store.all() if i.statement == "Use Poetry")
    store.decide([poetry.id], "reject")
    again = store.add(
        [
            draft("prefer UV.", evidence=(Evidence("s2", 3, "uv please"),)),  # same, reworded
            draft("Use poetry"),  # rejected before
            draft("Name things plainly"),
        ],
        "m",
    )
    uv = next(i for i in store.all() if i.statement == "Prefer uv")
    plainly = next(i for i in store.all() if i.statement == "Name things plainly")
    assert again == Added(new=(plainly.id,), merged=(uv.id,), skipped=1)
    assert uv.sessions == 2 and len(uv.evidence) == 2


def test_a_duplicate_by_id_merges_into_the_known_item(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "m.db")
    store.add([draft("Prefer uv")], "m")
    (uv,) = store.all()
    store.decide([uv.id], "accept")
    added = store.add(
        [
            draft(
                "Use uv for Python",
                relation="duplicate",
                related_id=uv.id,
                evidence=(Evidence("s9", 2, "uv"),),
            )
        ],
        "m",
    )
    assert added.merged == (uv.id,) and len(store.all()) == 1


def test_accepting_with_edits_and_retiring_what_an_update_replaces(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "m.db")
    store.add([draft("Prefer uv")], "m")
    (old,) = store.all()
    store.decide([old.id], "accept")
    store.add([draft("Prefer uv and ruff", relation="updates", related_id=old.id)], "m")
    new = next(i for i in store.all() if i.status == "candidate")
    store.decide([new.id], "accept", {new.id: ("Prefer uv, ruff and mypy", "/w/shop")})
    kept = store.get(new.id)
    assert kept is not None and kept.statement == "Prefer uv, ruff and mypy"
    assert kept.scope == "/w/shop" and kept.status == "accepted"
    retired = store.get(old.id)
    assert retired is not None and retired.status == "rejected"
    store.decide([old.id], "restore")
    restored = store.get(old.id)
    assert restored is not None and restored.status == "candidate"


def test_sessions_read_are_remembered(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "m.db")
    store.read([session("a"), session("b")])
    assert store.read_sessions() == {"a", "b"}


# The export


def test_markdown_has_one_section_per_category_for_one_scope(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "m.db")
    store.add(
        [
            draft("Prefer uv", category="tech", why="it is fast"),
            draft("Roles are Protocols"),
            draft("Shop runs on SQLite", kind="fact", scope="/w/shop"),
            draft("Not accepted"),
        ],
        "m",
    )
    accept = [i.id for i in store.all() if i.statement != "Not accepted"]
    store.decide(accept, "accept")
    text = markdown(store.all(), "preference", GLOBAL, "2026-11-18")
    assert text.startswith("# Preferences\n")
    assert text.index("## Architecture") < text.index("## Tech")
    assert "- Prefer uv. (it is fast)" in text and "Not accepted" not in text
    assert "SQLite" not in text  # another kind and scope
    facts = markdown(store.all(), "fact", "/w/shop")
    assert facts.startswith("# Facts: shop\n") and "- Shop runs on SQLite." in facts
    assert "Nothing accepted yet" in markdown(store.all(), "fact", GLOBAL)


# The pages


ANSWER = {
    "turns": [
        item(),
        item(
            kind="fact",
            scope="project",
            category="tech",
            statement="Shop stores data in SQLite",
            reveals="fact",
            quote="SQLite",
        ),
    ]
}


def viewer(tmp_path: Path, answer: dict[str, Any] | None = None) -> Viewer:
    bench = Workbench(
        FakeProvider(answer or ANSWER),
        tmp_path / "m.db",
        jobs=Jobs(synchronous=True),
        home=tmp_path,
    )
    return Viewer([FakeSource([session()])], bench=bench)


def post(
    app: Viewer, path: str, body: str, site: str = "same-origin"
) -> tuple[str, dict[str, str]]:
    seen: list[tuple[str, list[tuple[str, str]]]] = []
    data = body.encode()
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "HTTP_HOST": "127.0.0.1:8765",
        "HTTP_SEC_FETCH_SITE": site,
        "CONTENT_LENGTH": str(len(data)),
        "wsgi.input": io.BytesIO(data),
    }
    b"".join(app(environ, lambda status, h: seen.append((status, h))))  # type: ignore[arg-type]
    return seen[0][0], dict(seen[0][1])


def test_extract_then_review_accept_and_export(tmp_path: Path) -> None:
    app = viewer(tmp_path)
    pick = app.route("/knowledge/pick", "s=s1").body
    assert 'action="/knowledge/extract"' in pick and 'value="s1" ' in pick and " checked" in pick

    _, headers = post(app, "/knowledge/extract", "s=s1")
    done = app.route(headers["Location"], "")
    assert dict(done.headers)["Location"] == "/knowledge?extracted=1&new=1,2"
    assert "· read" in app.route("/knowledge/pick", "").body

    review = app.route("/knowledge", "extracted=1&new=1,2").body
    assert "2 new to review" in review and 'href="#k1">Go to the first' in review
    assert review.count('class="kn-row fresh"') == 2
    assert review.count('<span class="kn-fresh">New</span>') == 3  # the notice, and each row
    assert "Use typing.Protocol for roles, never ABCs</textarea>" in review
    assert "no, we use typing.Protocol" in review and 'href="/s/s1#t2"' in review
    assert '<option value="/w/shop">shop</option>' in review  # global, or this project

    protocol, sqlite = 1, 2
    body = (
        f"view=review&action=accept&id={protocol}"
        f"&text-{protocol}=Prefer+typing.Protocol+roles&scope-{protocol}=global"
    )
    status, headers = post(app, "/knowledge/decide", body)
    assert status == "303 See Other" and headers["Location"] == "/knowledge"
    post(app, "/knowledge/decide", f"view=review&one=reject:{sqlite}")

    accepted = app.route("/knowledge", "view=accepted").body
    assert "Prefer typing.Protocol roles</textarea>" in accepted
    assert app.route("/knowledge", "").body.count('class="kn-row"') == 0

    export = app.route("/knowledge/export", "").body
    assert "- Prefer typing.Protocol roles." in export and "@PREFERENCES.md" in export
    download = app.route("/knowledge/export/PREFERENCES.md", "scope=global")
    assert dict(download.headers)["Content-Disposition"] == 'attachment; filename="PREFERENCES.md"'
    assert "- Prefer typing.Protocol roles." in download.body


def test_extracting_again_does_not_bring_back_what_was_rejected(tmp_path: Path) -> None:
    app = viewer(tmp_path)
    post(app, "/knowledge/extract", "s=s1")
    post(app, "/knowledge/decide", "view=review&action=reject&id=1&id=2")
    _, headers = post(app, "/knowledge/extract", "s=s1")
    assert dict(app.route(headers["Location"], "").headers)["Location"] == (
        "/knowledge?extracted=1"
    )
    assert "Nothing new to review." in app.route("/knowledge", "extracted=1").body


def test_the_review_list_marks_what_the_last_extraction_brought(tmp_path: Path) -> None:
    app = viewer(tmp_path)
    post(app, "/knowledge/extract", "s=s1")
    marked = app.route("/knowledge", "new=2").body
    assert "new to review" not in marked  # marks without the announcement
    assert marked.count('class="kn-row fresh"') == 1 and 'id="k2"' in marked
    assert '<input type="hidden" name="new" value="2">' in marked
    # deciding one keeps the marks on the rest
    _, headers = post(app, "/knowledge/decide", "view=review&new=2&one=reject:1")
    assert headers["Location"] == "/knowledge?new=2"
    assert app.route("/knowledge", "new=2&merged=x,7").body.count('class="kn-row fresh"') == 1


def test_session_page_and_rail_lead_here(tmp_path: Path) -> None:
    body = viewer(tmp_path).route("/s/s1", "").body
    assert 'href="/knowledge/pick?s=s1"' in body and 'href="/knowledge"' in body


def test_posts_from_other_sites_are_refused(tmp_path: Path) -> None:
    status, _ = post(viewer(tmp_path), "/knowledge/decide", "action=accept&id=1", "cross-site")
    assert status == "403 Forbidden"


def test_without_a_workbench_there_is_no_knowledge_page() -> None:
    assert Viewer([FakeSource([session()])]).route("/knowledge", "").status == "404 Not Found"


def test_without_claude_code_extraction_is_offered_but_not_started(tmp_path: Path) -> None:
    bench = Workbench(FakeProvider(configured=False), tmp_path / "m.db")
    app = Viewer([FakeSource([session()])], bench=bench)
    page = app.route("/knowledge/pick", "").body
    assert "runs on Claude Code, which isn't installed here" in page
    assert "Install the fake model" in page
    _, headers = post(app, "/knowledge/extract", "s=s1")
    assert headers["Location"] == "/knowledge/pick?s=s1"


def test_turns_show_the_knowledge_they_became_and_link_to_it(tmp_path: Path) -> None:
    app = viewer(tmp_path)
    post(app, "/knowledge/extract", "s=s1")
    body = app.route("/s/s1", "").body
    turn = body[body.index('id="t2"') :]
    assert '<aside class="learned"' in turn
    assert 'href="/knowledge#k1"' in turn and "Use typing.Protocol for roles" in turn
    assert "2 became knowledge" in body
    # waiting items say so where you can act on them; the index marks the turn
    assert '<a class="state" href="/knowledge#k1">Review</a>' in turn
    assert '<span class="kn-mark" title="' in body[body.index('class="turn-list"') :]
    assert '<span class="n" title="waiting for review">2</span>' in body  # in the rail
    post(app, "/knowledge/decide", "view=review&one=reject:1")
    assert 'href="/knowledge#k1"' not in app.route("/s/s1", "").body  # rejected: gone


def test_instruction_files_already_written_reach_the_prompt(tmp_path: Path) -> None:
    project = tmp_path / "shop"
    project.mkdir()
    (project / "CLAUDE.md").write_text(f"Use SQLite.\nKEY={SECRET}\n")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("Answer briefly.")
    provider = FakeProvider(ANSWER)
    bench = Workbench(provider, tmp_path / "m.db", jobs=Jobs(synchronous=True), home=home)
    bench.extract([session(project=str(project))])
    _, user, _ = provider.requests[0]
    assert "<already_written>" in user and "Use SQLite." in user and "Answer briefly." in user
    assert SECRET not in user
    assert f'path="{project}/CLAUDE.md"' in user
