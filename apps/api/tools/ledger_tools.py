from __future__ import annotations

from datetime import date as date_module
from typing import List, Optional

from ..db.session import get_connection, init_db


def insert_entry(
    db_path: Optional[str],
    entry_date: str,
    item: str,
    amount: int,
    note: Optional[str] = None,
) -> dict:
    connection = get_connection(db_path)
    init_db(connection)
    cursor = connection.execute(
        "INSERT INTO ledger (date, item, amount, note) VALUES (?, ?, ?, ?)",
        (entry_date, item, amount, note),
    )
    connection.commit()
    entry_id = cursor.lastrowid
    if entry_id is None:
        raise RuntimeError("Failed to insert entry")
    entry = get_entry_by_id(db_path, entry_id)
    if entry is None:
        raise RuntimeError("Inserted entry not found")
    return entry


def list_entries(
    db_path: Optional[str],
    entry_date: Optional[str] = None,
    limit: int = 10,
) -> List[dict]:
    connection = get_connection(db_path)
    init_db(connection)
    if entry_date:
        rows = connection.execute(
            "SELECT * FROM ledger WHERE date = ? ORDER BY id DESC LIMIT ?",
            (entry_date, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_entry_by_id(db_path: Optional[str], entry_id: int) -> Optional[dict]:
    connection = get_connection(db_path)
    init_db(connection)
    row = connection.execute(
        "SELECT * FROM ledger WHERE id = ?",
        (entry_id,),
    ).fetchone()
    return dict(row) if row else None


def get_last_entry(db_path: Optional[str]) -> Optional[dict]:
    connection = get_connection(db_path)
    init_db(connection)
    row = connection.execute(
        "SELECT * FROM ledger ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def update_entry_amount(
    db_path: Optional[str],
    entry_id: int,
    new_amount: int,
) -> Optional[dict]:
    connection = get_connection(db_path)
    init_db(connection)
    connection.execute(
        "UPDATE ledger SET amount = ? WHERE id = ?",
        (new_amount, entry_id),
    )
    connection.commit()
    return get_entry_by_id(db_path, entry_id)


def delete_entry(db_path: Optional[str], entry_id: int) -> bool:
    connection = get_connection(db_path)
    init_db(connection)
    cursor = connection.execute(
        "DELETE FROM ledger WHERE id = ?",
        (entry_id,),
    )
    connection.commit()
    return cursor.rowcount > 0


def today_iso() -> str:
    return date_module.today().isoformat()
