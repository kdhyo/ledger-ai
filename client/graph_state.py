from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypedDict


class ChatState(TypedDict, total=False):
    message: str
    reply: str
    pending_confirm: Optional[dict]
    pending_action: Optional[dict]
    pending_selection: Optional[dict]
    intent: str
    intent_date: Optional[str]
    intent_item: Optional[str]
    intent_amount: Optional[int]
    intent_target: Optional[str]


@dataclass
class Intent:
    intent: str
    date: Optional[str] = None
    item: Optional[str] = None
    amount: Optional[int] = None
    target: Optional[str] = None
