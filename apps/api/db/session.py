from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Union

from .models import LEDGER_SCHEMA

ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT_DIR / "ledger.db"


def get_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.execute(LEDGER_SCHEMA)
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(ledger)").fetchall()
    }
    if "merchant" in columns and "item" not in columns:
        connection.execute("ALTER TABLE ledger RENAME COLUMN merchant TO item")
    connection.commit()
