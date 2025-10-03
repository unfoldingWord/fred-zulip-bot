from __future__ import annotations

from pathlib import Path

import pytest

from fred_zulip_bot.services.sql_service import SqlService


@pytest.fixture
def sql_service(tmp_path: Path) -> SqlService:
    ddl = tmp_path / "ddl.txt"
    ddl.write_text("table info")
    rules = tmp_path / "rules.txt"
    rules.write_text("rules info")
    return SqlService(ddl_path=ddl, rules_path=rules)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM projects",
        "select name FROM users WHERE id = 1",
    ],
)
def test_is_safe_sql_allows_selects(sql_service: SqlService, statement: str) -> None:
    assert sql_service.is_safe_sql(statement) is True  # noqa: S101


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE projects SET name='x'",
        "DELETE FROM users",
        "SELECT * FROM data; DROP TABLE data",
        "SELECT * FROM x WHERE name LIKE 'test';",
        "SELECT * FROM x -- comment",
        "SELECT * FROM x /* no */",
        "SELECT * INTO OUTFILE 'x' FROM y",
    ],
)
def test_is_safe_sql_rejects_dangerous_statements(sql_service: SqlService, statement: str) -> None:
    assert sql_service.is_safe_sql(statement) is False  # noqa: S101


@pytest.mark.parametrize(
    "statement",
    [
        "  ",
        "DESCRIBE table",
        "INSERT INTO table VALUES (1)",
    ],
)
def test_is_safe_sql_rejects_non_select(sql_service: SqlService, statement: str) -> None:
    assert sql_service.is_safe_sql(statement) is False  # noqa: S101
