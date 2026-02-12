from __future__ import annotations

import re
from typing import Optional

from .graph_state import ChatState


def cleanup_state() -> ChatState:
    return {"pending_confirm": None, "pending_action": None, "pending_selection": None}


def format_entries(entries: list[dict]) -> str:
    if not entries:
        return "내역이 없어요."
    lines = []
    for idx, entry in enumerate(entries, start=1):
        lines.append(f"{idx}) {entry['date']} {entry['item']} {entry['amount']}원 (id:{entry['id']})")
    return "\n".join(lines)


def filter_entries_by_item(entries: list[dict], item: Optional[str]) -> list[dict]:
    if not item:
        return entries
    needle = re.sub(r"\s+", "", item).lower()
    if not needle:
        return entries

    out = []
    for entry in entries:
        hay = re.sub(r"\s+", "", str(entry.get("item", ""))).lower()
        if needle in hay:
            out.append(entry)
    return out
