"""Migrate existing JSON chat histories into TinyDB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB

DEFAULT_SOURCE = Path("./data/chat_histories")
DEFAULT_DEST = Path("./data/history.json")
DEFAULT_TABLE = "history"
DEFAULT_MAX_LENGTH = 20


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Directory containing legacy JSON history files",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="Destination TinyDB file path",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help="TinyDB table name to use",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=DEFAULT_MAX_LENGTH,
        help="Maximum history length to retain per user",
    )
    args = parser.parse_args()

    source_dir = args.source
    db_path = args.dest
    table_name = args.table
    max_length = args.max_length

    if not source_dir.exists():
        raise SystemExit(f"source directory {source_dir} does not exist")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = TinyDB(db_path)
    table = db.table(table_name)
    query = Query()

    migrated = 0
    skipped = 0

    for file_path in sorted(source_dir.glob("*.json")):
        email = _unsanitize_email(file_path.stem)
        history = _load_history(file_path)
        if not history:
            skipped += 1
            continue

        trimmed = history[-max_length:]
        table.upsert({"email": email, "history": trimmed}, query.email == email)
        migrated += 1

    db.close()

    print(f"Migrated {migrated} histories into {db_path} (table {table_name}).")
    if skipped:
        print(f"Skipped {skipped} empty or unreadable files.")


def _load_history(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _unsanitize_email(value: str) -> str:
    return value.replace("_dot_", ".").replace("_at_", "@")


if __name__ == "__main__":
    main()
