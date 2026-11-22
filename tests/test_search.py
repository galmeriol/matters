"""Full-text search over asks, answers and work."""

from pathlib import Path

from matters.search import Results, excerpt, terms
from matters.session import Entry, Session, SourceRef, ToolCall

REF = SourceRef(Path("x.jsonl"), 1)


def session() -> Session:
    entries = (
        Entry("ask", "Why is the cache slow?", REF),
        Entry("tool", "", REF, ToolCall("Read", {"file_path": "/p/cache.py"}, "cache code here")),
        Entry("tool", "", REF, ToolCall("Bash", {"command": "pytest -k cache"}, "1 failed")),
        Entry("text", "The cache misses on every call.", REF),
    )
    return Session("s", "claude-code", Path("/p"), entries)


def test_terms_are_words_and_quoted_phrases_in_lower_case() -> None:
    assert terms('Cache "every call"  cache') == ("cache", "every call")


def test_hits_are_per_block_and_counted_by_kind() -> None:
    results = Results.search([session()], "cache")
    assert [(h.turn, h.where, h.label) for h in results.hits] == [
        (1, "ask", "You asked"),
        (1, "answer", "Answer"),  # what was said first, then the work
        (1, "work", "Read"),  # its input (the path), not the file it read
        (1, "work", "Bash"),
    ]
    assert results.counts == {"ask": 1, "answer": 1, "work": 2}
    assert Results.search([session()], "cache", "answer").hits[0].where == "answer"


def test_file_contents_that_were_only_read_are_not_searched() -> None:
    assert Results.search([session()], "code here").hits == ()


def test_every_word_must_be_in_the_same_block() -> None:
    assert len(Results.search([session()], "cache failed").hits) == 1  # the Bash step
    assert Results.search([session()], "slow misses").hits == ()


def test_excerpt_marks_every_term_and_says_where_it_was_cut() -> None:
    text = "word " * 100 + "the Cache misses " + "tail " * 100
    runs = excerpt(text, ("cache", "misses"), width=60)
    assert runs[0] == ("…", False) and runs[-1] == ("…", False)
    assert ("Cache", True) in runs and ("misses", True) in runs
