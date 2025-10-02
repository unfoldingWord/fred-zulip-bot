"""Filesystem-backed history repository."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fred_zulip_bot.adapters.history_repo.base import HistoryRepository


class FilesHistoryRepo(HistoryRepository):
    """Persist chat history as JSON files keyed by user email."""

    def __init__(
        self,
        base_dir: Path,
        max_length: int = 20,
        *,
        logger: Any | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._max_length = max_length
        self._logger = logger

    def get(self, email: str) -> list[dict[str, Any]]:
        path = self._path_for(email)
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            if self._logger is not None:
                self._logger.info(
                    "chat history for %s is corrupted. starting fresh.",
                    email,
                )
            return []

        if isinstance(data, list):
            return data  # legacy format: list[dict]

        return []

    def save(self, email: str, history: list[dict[str, Any]]) -> None:
        trimmed = history[-self._max_length :]
        path = self._path_for(email)
        path.write_text(json.dumps(trimmed, indent=2))

    def _path_for(self, email: str) -> Path:
        safe_email = email.replace("@", "_at_").replace(".", "_dot_")
        return self._base_dir / f"{safe_email}.json"
