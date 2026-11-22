"""Every player of a role, fakes included, must honour it."""

import pytest

from matters.knowledge.extractor import Extractor, LlmExtractor
from matters.llm import Provider
from matters.llm.claude_code import ClaudeCodeProvider
from matters.sources import Source
from matters.sources.claude_code import ClaudeCode
from tests.fakes import FIXTURES, FakeExtractor, FakeProvider, FakeSource


@pytest.mark.parametrize("player", [ClaudeCode(root=FIXTURES / "claude"), FakeSource([])])
def test_plays_the_source_role(player: object) -> None:
    assert isinstance(player, Source)


@pytest.mark.parametrize("player", [ClaudeCodeProvider(), FakeProvider()])
def test_plays_the_provider_role(player: object) -> None:
    assert isinstance(player, Provider)


@pytest.mark.parametrize("player", [LlmExtractor(FakeProvider()), FakeExtractor()])
def test_plays_the_extractor_role(player: object) -> None:
    assert isinstance(player, Extractor)
