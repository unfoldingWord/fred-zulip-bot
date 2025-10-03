from __future__ import annotations

from typing import Any

import pytest

from fred_zulip_bot.adapters.mysql_client import MySqlClient


class DummyCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.executed_sql: str | None = None

    def execute(self, sql: str) -> None:
        self.executed_sql = sql

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def close(self) -> None:  # pragma: no cover - no behavior
        pass


class DummyConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.closed = False
        self.cursor_obj = DummyCursor(rows)

    def cursor(self) -> DummyCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


class DummyLogger:
    def __init__(self) -> None:
        self.logged = False

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.logged = True


def test_mysql_client_select_success(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [(1,), (2,)]
    connection = DummyConnection(rows)
    monkeypatch.setattr(
        "fred_zulip_bot.adapters.mysql_client.MYSQL_CONNECTOR",
        type("Connector", (), {"connect": staticmethod(lambda **kwargs: connection)}),
    )

    client = MySqlClient(
        host="host",
        database="db",
        user="user",
        password="test-pw",  # noqa: S106
        logger=DummyLogger(),
    )

    result = client.select("SELECT 1")

    assert result.strip() == "(1,), (2,),"  # noqa: S101
    assert connection.cursor_obj.executed_sql == "SELECT 1"  # noqa: S101
    assert connection.closed is True  # noqa: S101


def test_mysql_client_select_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fred_zulip_bot.adapters.mysql_client.MYSQL_CONNECTOR",
        type(
            "Connector",
            (),
            {"connect": staticmethod(lambda **kwargs: (_ for _ in ()).throw(RuntimeError("fail")))},
        ),
    )

    logger = DummyLogger()
    client = MySqlClient(
        host="host",
        database="db",
        user="user",
        password="test-pw",  # noqa: S106
        logger=logger,
    )

    result = client.select("SELECT 1")

    assert result == "salvage"  # noqa: S101
    assert logger.logged is True  # noqa: S101
