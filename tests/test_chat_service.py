from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import BackgroundTasks, HTTPException

from fred_zulip_bot.core.models import ChatRequest, ZulipMessage
from fred_zulip_bot.services import intent_service
from fred_zulip_bot.services.chat_service import DEFAULT_FALLBACK_MESSAGE, ChatService
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
    sql_rewrite_text: str | None = None,
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
    if sql_rewrite_text is not None:
        mapping[sql_service.sql_rewrite_prompt] = sql_rewrite_text
    if summary_text is not None:
        mapping[sql_service.answer_prompt] = summary_text

    call_log: list[dict[str, Any]] = []

    def fake_ask_model(
        self,
        message,
        prompt,
        use_history,
        *,
        model_override=None,
        allow_fallback=True,
        generation_config=None,
    ):  # type: ignore[override]
        try:
            text = mapping[prompt]
        except KeyError as exc:  # pragma: no cover - guard
            raise AssertionError(f"Unexpected prompt: {prompt!r}") from exc
        call_log.append(
            {
                "prompt": prompt,
                "content": message.content,
                "use_history": use_history,
                "generation_config": dict(generation_config) if generation_config else None,
            }
        )
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
        history_max_length=7,
    )

    service._test_ask_calls = call_log  # type: ignore[attr-defined]

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
        intent_label="converse_with_fred_bot",
        chatbot_reply="Hello there",
    )

    service.process_user_message(make_request("hi"))

    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [  # noqa: S101
        "Figuring out the best way to help.",
        "Drafting a reply about how I work.",
        "Hello there",
    ]
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == ["Hello there"]  # noqa: S101


def test_process_user_message_database_flow(monkeypatch, sql_service):
    service, zulip, history, mysql, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="query_fred",
        sql_text='{"sql": "SELECT 1"}',
        db_result="(1,)",
        summary_text="There is one result.",
    )

    service.process_user_message(make_request("how many?"))

    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [  # noqa: S101
        "Figuring out the best way to help.",
        "Checking the database for the details you asked about. This could take some time. Thanks for your patience.",
        "I have the data - summarizing it for you now...",
        "There is one result.",
    ]
    assert mysql.last_query == "SELECT 1"  # noqa: S101
    saved = history.get("user@example.com")
    parts_list = [entry.get("parts") for entry in saved if entry.get("parts")]
    assert parts_list[-1] == ["There is one result."]  # noqa: S101
    assert all("SELECT" not in parts[0] for parts in parts_list)  # noqa: S101


def test_query_fred_preprocesses_follow_up(monkeypatch, sql_service):
    rewrite_json = '{"rewritten_request": "List the translation projects in Maryland."}'
    sql_json = '{"sql": "SELECT * FROM projects WHERE state = \'Maryland\'"}'

    service, _, _, mysql, logger = build_service(
        monkeypatch,
        sql_service,
        intent_label="query_fred",
        sql_rewrite_text=rewrite_json,
        sql_text=sql_json,
        db_result="rows",
        summary_text="Summarized",
    )

    history_entries = [
        {"role": "user", "parts": ["What are all the translation projects in Virginia?"]},
        {"role": "model", "parts": ["Previously answered"]},
        {"role": "user", "parts": ["and in Maryland?"]},
    ]
    message = ZulipMessage(
        content="and in Maryland?",
        display_recipient="stream",
        sender_email="user@example.com",
        subject="topic",
        type="stream",
    )

    response_text, sql_text, db_data = service.query_fred(message, history_entries)

    expected_sql = "SELECT * FROM projects WHERE state = 'Maryland'"
    assert mysql.last_query == expected_sql  # noqa: S101
    assert sql_text == expected_sql  # noqa: S101
    assert db_data == "rows"  # noqa: S101
    assert response_text == "Summarized"  # noqa: S101

    before_entry = next(
        entry for entry in logger.infos if entry[0].startswith("SQL preprocess before")
    )
    assert before_entry[1][0] == 2  # noqa: S101

    after_entry = next(
        entry for entry in logger.infos if entry[0].startswith("SQL preprocess after")
    )
    assert after_entry[1][0] is True  # noqa: S101

    ask_calls = service._test_ask_calls
    assert ask_calls[0]["prompt"] == sql_service.sql_rewrite_prompt  # noqa: S101
    assert "Conversation history" in ask_calls[0]["content"]  # noqa: S101
    assert ask_calls[0]["use_history"] is False  # noqa: S101
    assert ask_calls[0]["generation_config"]["response_mime_type"] == "application/json"  # noqa: S101

    assert ask_calls[1]["prompt"] == sql_service.sql_prompt  # noqa: S101
    assert ask_calls[1]["content"] == "List the translation projects in Maryland."  # noqa: S101
    assert ask_calls[1]["use_history"] is False  # noqa: S101
    schema = ask_calls[1]["generation_config"]["response_schema"]
    assert schema == sql_service.sql_generation_schema  # noqa: S101

    assert ask_calls[2]["prompt"] == sql_service.answer_prompt  # noqa: S101
    assert ask_calls[2]["generation_config"] is None  # noqa: S101


def test_process_user_message_other(monkeypatch, sql_service):
    service, zulip, history, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="handle_unsupported_function",
        other_reply="Cannot help",
    )

    service.process_user_message(make_request("other question"))

    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [  # noqa: S101
        "Figuring out the best way to help.",
        "Working on a helpful explanation since I can't do that directly.",
        "Cannot help",
    ]
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == ["Cannot help"]  # noqa: S101


def test_handle_chat_request_rejects_invalid_token(monkeypatch, sql_service):
    service, _, _, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="converse_with_fred_bot",
        chatbot_reply="Hi",
    )

    request = make_request("hi")
    request.token = "bad"  # noqa: S105

    with pytest.raises(HTTPException) as exc:
        service.handle_chat_request(request, BackgroundTasks())

    assert exc.value.status_code == 401  # noqa: S101


def test_handle_chat_request_sends_ack(monkeypatch, sql_service):
    service, zulip, _, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="converse_with_fred_bot",
        chatbot_reply="unused",
    )

    request = make_request("hi")

    service.handle_chat_request(request, BackgroundTasks())

    assert zulip.sent[0]["content"] == "thinking..."  # noqa: S101


def test_process_user_message_database_salvage(monkeypatch, sql_service):
    service, zulip, history, mysql, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="query_fred",
        sql_text='{"sql": "SELECT name"}',
        db_result="salvage",
        summary_text="Use fallback",
    )

    service.process_user_message(make_request("fallback?"))

    assert mysql.last_query == "SELECT name"  # noqa: S101
    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [  # noqa: S101
        "Figuring out the best way to help.",
        "Checking the database for the details you asked about. This could take some time. Thanks for your patience.",
        "I have the data - summarizing it for you now...",
        "Use fallback",
    ]
    saved = history.get("user@example.com")
    parts_list = [entry.get("parts") for entry in saved if entry.get("parts")]
    assert parts_list[-1] == ["Use fallback"]  # noqa: S101
    assert all("SELECT" not in parts[0] for parts in parts_list)  # noqa: S101


def test_process_user_message_unsafe_sql(monkeypatch, sql_service):
    service, zulip, history, mysql, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="query_fred",
        sql_text='{"sql": "Not SQL"}',
        summary_text="unused",
    )

    monkeypatch.setattr(service._sql_service, "is_safe_sql", lambda _: False)

    service.process_user_message(make_request("unsafe"))

    friendly = DEFAULT_FALLBACK_MESSAGE
    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [  # noqa: S101
        "Figuring out the best way to help.",
        "Checking the database for the details you asked about. This could take some time. Thanks for your patience.",
        "That request looked unsafe, so I'm sending a fallback instead.",
        friendly,
    ]
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == [friendly]  # noqa: S101
    assert not hasattr(mysql, "last_query")  # noqa: S101


def test_process_user_message_failure_sends_fallback(monkeypatch, sql_service):
    service, zulip, history, _, logger = build_service(
        monkeypatch,
        sql_service,
        intent_label="converse_with_fred_bot",
        chatbot_reply="unused",
    )

    def explode(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_run_legacy_flow", explode)

    service.process_user_message(make_request("hi"))

    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [DEFAULT_FALLBACK_MESSAGE]  # noqa: S101
    saved = history.get("user@example.com")
    assert saved[-1]["parts"] == [DEFAULT_FALLBACK_MESSAGE]  # noqa: S101
    assert any("Processing user message failed" in entry[0] for entry in logger.errors)  # noqa: S101


def test_process_user_message_retries_on_send_failure(monkeypatch, sql_service):
    service, _, history, _, logger = build_service(
        monkeypatch,
        sql_service,
        intent_label="converse_with_fred_bot",
        chatbot_reply="Hello",
    )

    attempts: list[dict[str, Any]] = []
    failed_final = {"value": False}

    def flaky_send(**kwargs: Any) -> None:
        if kwargs.get("content") == "Hello" and not failed_final["value"]:
            failed_final["value"] = True
            raise RuntimeError("network glitch")
        attempts.append(kwargs)

    monkeypatch.setattr(service._zulip_client, "send", flaky_send)

    service.process_user_message(make_request("hi"))

    contents = [entry["content"] for entry in attempts]
    assert contents[-1] == "Hello"  # noqa: S101
    assert history.get("user@example.com")[-1]["parts"] == ["Hello"]  # noqa: S101
    assert failed_final["value"] is True  # noqa: S101
    assert len(logger.errors) == 1  # noqa: S101


@pytest.mark.skipif(sys.version_info < (3, 10), reason="LangGraph requires Python >= 3.10")
def test_process_user_message_with_langgraph(monkeypatch, sql_service):
    service, zulip, history, _, _ = build_service(
        monkeypatch,
        sql_service,
        intent_label="converse_with_fred_bot",
        chatbot_reply="LangGraph reply",
        use_langgraph=True,
    )

    service.process_user_message(make_request("hi"))

    contents = [entry["content"] for entry in zulip.sent]
    assert contents == [  # noqa: S101
        "Figuring out the best way to help.",
        "Drafting a reply about how I work.",
        "LangGraph reply",
    ]
    assert history.get("user@example.com")[-1]["parts"] == ["LangGraph reply"]  # noqa: S101
