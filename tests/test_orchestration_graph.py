from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import pytest

if sys.version_info < (3, 10):  # pragma: no cover - compatibility guard  # noqa: UP036
    pytest.skip("LangGraph requires Python >= 3.10", allow_module_level=True)

from fred_zulip_bot.core.models import ChatRequest, ZulipMessage
from fred_zulip_bot.orchestration.graph import GraphState, build_chat_graph
from fred_zulip_bot.services.intent_service import IntentType


@dataclass
class StubService:
    intents: list[IntentType]
    responses: dict[IntentType, tuple[str, str, str]]
    calls: list[str] = field(default_factory=list)

    def classify_intent(self, message: ZulipMessage) -> IntentType:
        self.calls.append(f"classify:{message.content}")
        return self.intents.pop(0)

    def handle_chatbot(self, message: ZulipMessage, history: list[dict[str, Any]]) -> str:
        self.calls.append("chatbot")
        return self.responses[IntentType.CHATBOT][0]

    def handle_other(self, message: ZulipMessage, history: list[dict[str, Any]]) -> str:
        self.calls.append("other")
        return self.responses[IntentType.OTHER][0]

    def handle_database(
        self, message: ZulipMessage, history: list[dict[str, Any]]
    ) -> tuple[str, str, str]:
        self.calls.append("database")
        return self.responses[IntentType.DATABASE]


class DummyLogger:
    def __init__(self) -> None:
        self.events: list[str] = []

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.events.append(message % args if args else message)


def make_request(content: str) -> ChatRequest:
    return ChatRequest(
        message=ZulipMessage(
            content=content,
            display_recipient="stream",
            sender_email="user@example.com",
            subject="topic",
            type="stream",
        ),
        token="token",  # noqa: S106
    )


def test_graph_routes_chatbot() -> None:
    service = StubService(
        intents=[IntentType.CHATBOT],
        responses={
            IntentType.CHATBOT: ("hi", "", ""),
            IntentType.OTHER: ("", "", ""),
            IntentType.DATABASE: ("", "", ""),
        },
    )
    logger = DummyLogger()
    runner = build_chat_graph(chat_service=service, logger=logger)

    result = runner.invoke(GraphState(request=make_request("hello"), history=[], intent=None))

    assert result["response"] == "hi"  # noqa: S101
    assert "chatbot" in service.calls  # noqa: S101


def test_graph_routes_database() -> None:
    service = StubService(
        intents=[IntentType.DATABASE],
        responses={
            IntentType.CHATBOT: ("", "", ""),
            IntentType.OTHER: ("", "", ""),
            IntentType.DATABASE: ("answer", "SQL", "RESULT"),
        },
    )
    logger = DummyLogger()
    runner = build_chat_graph(chat_service=service, logger=logger)

    result = runner.invoke(GraphState(request=make_request("data"), history=[], intent=None))

    assert result["response"] == "answer"  # noqa: S101
    assert result["sql"] == "SQL"  # noqa: S101
    assert result["result"] == "RESULT"  # noqa: S101


def test_graph_default_to_other() -> None:
    service = StubService(
        intents=[IntentType.OTHER],
        responses={
            IntentType.CHATBOT: ("", "", ""),
            IntentType.OTHER: ("fallback", "", ""),
            IntentType.DATABASE: ("", "", ""),
        },
    )
    logger = DummyLogger()
    runner = build_chat_graph(chat_service=service, logger=logger)

    result = runner.invoke(GraphState(request=make_request("unknown"), history=[], intent=None))

    assert result["response"] == "fallback"  # noqa: S101
