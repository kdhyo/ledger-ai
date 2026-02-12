from __future__ import annotations

from datetime import date as date_module


def today_iso() -> str:
    return date_module.today().isoformat()
