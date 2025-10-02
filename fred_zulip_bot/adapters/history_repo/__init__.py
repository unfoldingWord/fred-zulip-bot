"""History repository abstractions."""

from fred_zulip_bot.adapters.history_repo.files_repo import FilesHistoryRepo
from fred_zulip_bot.adapters.history_repo.tinydb_repo import TinyDbHistoryRepo

__all__ = ["FilesHistoryRepo", "TinyDbHistoryRepo"]
