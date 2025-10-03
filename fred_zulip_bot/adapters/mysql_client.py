"""MySQL read-only client."""

from __future__ import annotations

from importlib import import_module
from typing import Any

try:
    MYSQL_CONNECTOR: Any = import_module("mysql.connector")
except ModuleNotFoundError as exc:  # pragma: no cover - hard dependency
    raise RuntimeError("mysql-connector-python is required to use MySqlClient") from exc


class MySqlClient:
    """Execute read-only queries against the configured database."""

    def __init__(
        self,
        *,
        host: str,
        database: str,
        user: str,
        password: str,
        port: int = 3306,
        logger: Any | None = None,
    ) -> None:
        self._host = host
        self._database = database
        self._user = user
        self._password = password
        self._port = port
        self._logger = logger

    def select(self, sql: str) -> str:
        try:
            conn = MYSQL_CONNECTOR.connect(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                charset="utf8mb4",
                collation="utf8mb4_unicode_ci",
            )

            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            result = ""
            for row in rows:
                result += f"{row}, "

            cursor.close()
            conn.close()
            return result
        except Exception:
            if self._logger is not None:
                self._logger.error("invalid sql generated", exc_info=True)
            return "salvage"
