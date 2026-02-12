from __future__ import annotations

from typing import Optional

from .tools.ledger_tools import list_entries, sum_entries


LEDGER_SCHEMA_RESOURCE = """table: ledger
columns:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- date TEXT NOT NULL (YYYY-MM-DD)
- item TEXT NOT NULL
- amount INTEGER NOT NULL
- note TEXT NULLABLE
- created_at TEXT NOT NULL
"""


def get_ledger_schema_resource() -> str:
    return LEDGER_SCHEMA_RESOURCE


def build_read_resource_context(
    db_path: Optional[str],
    entry_date: Optional[str],
    limit: int = 5,
) -> str:
    rows = list_entries(db_path, entry_date=entry_date, limit=limit)
    total = sum_entries(db_path, entry_date=entry_date)

    if rows:
        recent_lines = [f"- {row['date']} {row['item']} {row['amount']}" for row in rows]
        recent_text = "\n".join(recent_lines)
    else:
        recent_text = "- (none)"

    date_label = entry_date or "all"
    return (
        f"{get_ledger_schema_resource()}\n"
        f"recent_entries(limit={limit}, date={date_label}):\n{recent_text}\n"
        f"sum(date={date_label}): {total}"
    )
