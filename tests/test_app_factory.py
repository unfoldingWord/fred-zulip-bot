from __future__ import annotations

import importlib
from typing import Any

import pytest


class DummyHistoryRepo:
    def __init__(self, path, *, max_length, logger):  # type: ignore[override]
        self.path = path
        self.max_length = max_length
        self.logger = logger


class DummyZulipClient:
    def __init__(self, **_: Any) -> None:
        pass


class DummyMySqlClient:
    def __init__(self, **_: Any) -> None:
        pass


class DummyChatService:
    def __init__(self, **_: Any) -> None:
        pass

    def handle_chat_request(self, request, background_tasks):  # pragma: no cover
        raise NotImplementedError


class DummyConfig:
    TEST_MODE = True
    ZULIP_BOT_EMAIL_TEST = "bot@example.com"
    ZULIP_BOT_TOKEN_TEST = "token"  # noqa: S105
    ZULIP_AUTH_TOKEN_TEST = "auth"  # noqa: S105
    ZULIP_SITE = "https://example.com"
    DB_HOST = "localhost"
    DB_NAME = "db"
    DB_USER = "user"
    DB_PASSWORD = "pw"  # noqa: S105
    GENAI_API_KEY = "key"
    HISTORY_DB_PATH = "history.json"
    HISTORY_MAX_LENGTH = 5
    ENABLE_LANGGRAPH = False


@pytest.fixture
def app_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZULIP_BOT_TOKEN", "token")
    monkeypatch.setenv("ZULIP_BOT_EMAIL", "bot@example.com")
    monkeypatch.setenv("ZULIP_SITE", "https://example.com")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "db")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "pw")
    monkeypatch.setenv("GENAI_API_KEY", "key")
    monkeypatch.setenv("ZULIP_AUTH_TOKEN", "auth")

    module = importlib.import_module("fred_zulip_bot.apps.api.app")
    module = importlib.reload(module)
    return module


def test_create_app_sets_up_services(monkeypatch: pytest.MonkeyPatch, app_module) -> None:
    monkeypatch.setattr(app_module, "TinyDbHistoryRepo", DummyHistoryRepo)
    monkeypatch.setattr(app_module, "ZulipClient", DummyZulipClient)
    monkeypatch.setattr(app_module, "MySqlClient", DummyMySqlClient)
    monkeypatch.setattr(app_module, "ChatService", DummyChatService)
    monkeypatch.setattr(app_module, "config", DummyConfig)

    app = app_module.create_app()

    assert "chat_service" in app.state.services  # noqa: S101
    assert app.state.services["history_repo"].max_length == DummyConfig.HISTORY_MAX_LENGTH  # noqa: S101
