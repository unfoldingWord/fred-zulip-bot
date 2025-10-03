from __future__ import annotations

from dataclasses import dataclass

from fred_zulip_bot.services.intent_service import IntentType, classify_intent


@dataclass
class DummyReply:
    text: str


def make_asker(result: str):
    def ask(prompt: str, use_history: bool) -> DummyReply:
        return DummyReply(result)

    return ask


def test_classify_intent_database_label() -> None:
    intent = classify_intent(make_asker("database"))
    assert intent is IntentType.DATABASE  # noqa: S101


def test_classify_intent_trims_and_lowercases() -> None:
    intent = classify_intent(make_asker("  ChatBot\n"))
    assert intent is IntentType.CHATBOT  # noqa: S101


def test_classify_intent_defaults_to_other() -> None:
    intent = classify_intent(make_asker("something else"))
    assert intent is IntentType.OTHER  # noqa: S101
