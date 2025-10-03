from __future__ import annotations

from pathlib import Path

from fred_zulip_bot.adapters.history_repo.tinydb_repo import TinyDbHistoryRepo


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, message: str, *args, **kwargs) -> None:
        self.messages.append(message % args if args else message)


def test_tinydb_history_repo_roundtrip(tmp_path: Path) -> None:
    repo = TinyDbHistoryRepo(tmp_path / "history.json", max_length=2, logger=DummyLogger())

    assert repo.get("user@example.com") == []  # noqa: S101

    sample = [
        {"role": "user", "parts": ["hi"]},
        {"role": "model", "parts": ["hello"]},
        {"role": "user", "parts": ["follow-up"]},
    ]

    repo.save("user@example.com", sample)
    saved = repo.get("user@example.com")

    assert len(saved) == 2  # noqa: S101
    assert saved[0]["parts"] == ["hello"]  # noqa: S101
    assert saved[1]["parts"] == ["follow-up"]  # noqa: S101


def test_tinydb_history_repo_handles_malformed(tmp_path: Path) -> None:
    logger = DummyLogger()
    repo = TinyDbHistoryRepo(tmp_path / "history.json", max_length=2, logger=logger)

    repo._table.insert({"email": "user@example.com", "history": "oops"})

    assert repo.get("user@example.com") == []  # noqa: S101
    assert logger.messages  # noqa: S101
