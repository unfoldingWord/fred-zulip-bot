from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import BackgroundTasks, HTTPException

from fred_zulip_bot.core.models import ChatRequest, ZulipMessage
from fred_zulip_bot.services import intent_service
from fred_zulip_bot.services.chat_service import ChatService
from fred_zulip_bot.services.sql_service import SqlService


@dataclass
class FakeHistoryRepo:
    store: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def get(self, email: str) -> list[dict[str, Any]]:
        return list(self.store.get(email, []))

    def save(self, email: str, history: list[dict[str, Any]]) -> None:
        self.store[email] = list(history)


@dataclass
class FakeZulipClient:
    sent: list[dict[str, Any]] = field(default_factory=list)

    def send(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


@dataclass
class FakeMySqlClient:
    result: str

    def __init__(self, result: str) -> None:
        self.result = result

    def select(self, sql: str) -> str:
        self.last_query = sql
        return self.result


class DummyLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.errors: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.infos.append((message, args, kwargs))

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.errors.append((message, args, kwargs))


class DummyReply:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def sql_service(tmp_path):
    ddl = tmp_path / "ddl.txt"
    ddl.write_text("ddl")
    rules = tmp_path / "rules.txt"
    rules.write_text("rules")
    return SqlService(ddl_path=ddl, rules_path=rules)


def build_service(
    monkeypatch: pytest.MonkeyPatch,
    sql_service: SqlService,
    *,
    intent_label: str,
    chatbot_reply: str | None = None,
    other_reply: str | None = None,
    sql_text: str | None = None,
    db_result: str = "rows",
    summary_text: str | None = None,
    use_langgraph: bool = False,
) -> tuple[ChatService, FakeZulipClient, FakeHistoryRepo, FakeMySqlClient, DummyLogger]:
    monkeypatch.setattr(ChatService, "_configure_genai", lambda self, api_key: None)

    mapping: dict[str, str] = {intent_service.INTENT_PROMPT: intent_label}

    if chatbot_reply is not None:
        mapping[intent_service.CHATBOT_PROMPT] = chatbot_reply
    if other_reply is not None:
        mapping[intent_service.OTHER_PROMPT] = other_reply
    if sql_text is not None:
        mapping[sql_service.sql_prompt] = sql_text
    if summary_text is not None:
        mapping[sql_service.answer_prompt] = summary_text

    def fake_ask_model(
        self, message, prompt, use_history, *, model_override=None, allow_fallback=True
    ):  # type: ignore[override]
        try:
            text = mapping[prompt]
        except KeyError as exc:  # pragma: no cover - guard
            raise AssertionError(f"Unexpected prompt: {prompt!r}") from exc
        return DummyReply(text)

    monkeypatch.setattr(ChatService, "_ask_model", fake_ask_model)

    fake_history = FakeHistoryRepo()
    fake_zulip = FakeZulipClient()
    fake_mysql = FakeMySqlClient(db_result)
    logger = DummyLogger()

    service = ChatService(
        zulip_client=fake_zulip,
        history_repo=fake_history,
        mysql_client=fake_mysql,
        sql_service=sql_service,
        auth_token="secret",  # noqa: S106
        logger=logger,
        api_key="api-key",
        enable_langgraph=use_langgraph,
    )

    return service, fake_zulip, fake_history, fake_mysql, logger


def make_request(content: str) -> ChatRequest:
    message = ZulipMessage(
        content=content,
        display_recipient="stream",
        sender_email="user@example.com",
        subject="topic",
        type="stream",
    )
    return ChatRequest(message=message, token="secret")  # noqa: S106


def test_process_user_message_chatbot(monkeypatch, sql_service):
    service, zulip, history, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="chatbot",
        chatbot_reply="Hello there",
    )

    service.process_user_message(make_request("hi"))

    assert zulip.sent[0]["content"] == "Hello there"  # noqa: S101
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == ["Hello there"]  # noqa: S101


def test_process_user_message_database_flow(monkeypatch, sql_service):
    service, zulip, history, mysql, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="database",
        sql_text="SELECT 1",
        db_result="(1,)",
        summary_text="There is one result.",
    )

    service.process_user_message(make_request("how many?"))

    assert mysql.last_query == "SELECT 1"  # noqa: S101
    assert zulip.sent[0]["content"] == "There is one result."  # noqa: S101
    saved = history.get("user@example.com")
    parts_list = [entry.get("parts") for entry in saved if entry.get("parts")]
    assert parts_list[-1] == ["There is one result."]  # noqa: S101
    assert all("SELECT" not in parts[0] for parts in parts_list)  # noqa: S101


def test_process_user_message_other(monkeypatch, sql_service):
    service, zulip, history, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="other",
        other_reply="Cannot help",
    )

    service.process_user_message(make_request("other question"))

    assert zulip.sent[0]["content"] == "Cannot help"  # noqa: S101
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == ["Cannot help"]  # noqa: S101


def test_handle_chat_request_rejects_invalid_token(monkeypatch, sql_service):
    service, _, _, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="chatbot",
        chatbot_reply="Hi",
    )

    request = make_request("hi")
    request.token = "bad"  # noqa: S105

    with pytest.raises(HTTPException) as exc:
        service.handle_chat_request(request, BackgroundTasks())

    assert exc.value.status_code == 401  # noqa: S101


def test_process_user_message_database_salvage(monkeypatch, sql_service):
    service, zulip, history, mysql, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="database",
        sql_text="SELECT name",
        db_result="salvage",
        summary_text="Use fallback",
    )

    service.process_user_message(make_request("fallback?"))

    assert mysql.last_query == "SELECT name"  # noqa: S101
    assert zulip.sent[0]["content"] == "Use fallback"  # noqa: S101
    saved = history.get("user@example.com")
    parts_list = [entry.get("parts") for entry in saved if entry.get("parts")]
    assert parts_list[-1] == ["Use fallback"]  # noqa: S101
    assert all("SELECT" not in parts[0] for parts in parts_list)  # noqa: S101


def test_process_user_message_unsafe_sql(monkeypatch, sql_service):
    service, zulip, history, mysql, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="database",
        sql_text="Not SQL",
        summary_text="unused",
    )

    monkeypatch.setattr(service._sql_service, "is_safe_sql", lambda _: False)

    service.process_user_message(make_request("unsafe"))

    friendly = "I'm having trouble responding right now. Please report this to my creators."
    assert zulip.sent[0]["content"] == friendly  # noqa: S101
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == [friendly]  # noqa: S101
    assert not hasattr(mysql, "last_query")  # noqa: S101


@pytest.mark.skipif(sys.version_info < (3, 10), reason="LangGraph requires Python >= 3.10")
def test_process_user_message_with_langgraph(monkeypatch, sql_service):
    service, zulip, history, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="chatbot",
        chatbot_reply="LangGraph reply",
        use_langgraph=True,
    )

    service.process_user_message(make_request("hi"))

    assert zulip.sent[0]["content"] == "LangGraph reply"  # noqa: S101
    assert history.get("user@example.com")[-1]["parts"] == ["LangGraph reply"]  # noqa: S101
