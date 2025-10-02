"""Protocol definition for chat history repositories."""

from __future__ import annotations

from typing import Any, Protocol


class HistoryRepository(Protocol):
    """Storage abstraction for persisting chat history per user."""

    def get(self, email: str) -> list[dict[str, Any]]:
        """Return the stored history for the given email address."""

    def save(self, email: str, history: list[dict[str, Any]]) -> None:
        """Persist the provided history for the given email address."""
