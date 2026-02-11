from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class PendingConfirm(BaseModel):
    token: str
    prompt: str


class ChatResponse(BaseModel):
    reply: str
    pending_confirm: Optional[PendingConfirm] = None


class ConfirmRequest(BaseModel):
    token: str
    decision: Literal["yes", "no"]
