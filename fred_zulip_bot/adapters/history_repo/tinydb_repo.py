"""TinyDB-backed history repository implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB

from fred_zulip_bot.adapters.history_repo.base import HistoryRepository


class TinyDbHistoryRepo(HistoryRepository):
    """Persist chat histories in a TinyDB document store."""

    def __init__(
        self,
        db_path: Path,
        *,
        max_length: int = 20,
        table_name: str = "history",
        logger: Any | None = None,
    ) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(self._db_path)
        self._table = self._db.table(table_name)
        self._max_length = max_length
        self._logger = logger
        self._query = Query()

    def get(self, email: str) -> list[dict[str, Any]]:
        record = self._table.get(self._query.email == email)
        if record is None:
            return []

        if not isinstance(record, dict):
            if self._logger is not None:
                self._logger.warning("history record for %s is malformed; resetting", email)
            return []

        history = record.get("history", [])
        if isinstance(history, list):
            return [item for item in history if isinstance(item, dict)]

        if self._logger is not None:
            self._logger.warning("history record for %s is malformed; resetting", email)
        return []

    def save(self, email: str, history: list[dict[str, Any]]) -> None:
        trimmed = history[-self._max_length :]
        self._table.upsert(
            {"email": email, "history": trimmed},
            self._query.email == email,
        )

    def close(self) -> None:
        """Close the underlying TinyDB instance."""

        self._db.close()
