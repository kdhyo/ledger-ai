from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import re
import uuid

from .graph import build_graph, format_entries, load_prompt
from .llm import get_llm
from .schemas import ChatRequest, ChatResponse, ConfirmRequest, PendingConfirm
from .tools.ledger_tools import delete_entry, update_entry_amount


def create_app(db_path: Optional[str] = None, use_fake_llm: bool = False) -> FastAPI:
    app = FastAPI()
    root_dir = Path(__file__).resolve().parents[2]
    static_dir = root_dir / "apps" / "api" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.state.db_path = db_path
    app.state.pending_actions = {}
    app.state.pending_selection = None
    llm = get_llm(use_fake=use_fake_llm)
    prompt = load_prompt()
    app.state.graph = build_graph(db_path, llm, prompt)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest) -> ChatResponse:
        pending_selection = app.state.pending_selection if hasattr(app.state, "pending_selection") else None
        if pending_selection:
            message = payload.message
            if "취소" in message:
                app.state.pending_selection = None
                return ChatResponse(reply="선택을 취소했어요.", pending_confirm=None)

            match = re.search(r"(\d+)", message)
            if not match:
                return ChatResponse(
                    reply="id를 알려주세요.\n" + format_entries(pending_selection["candidates"]),
                    pending_confirm=None,
                )
            entry_id = int(match.group(1))
            candidate = next(
                (item for item in pending_selection["candidates"] if item["id"] == entry_id),
                None,
            )
            if not candidate:
                return ChatResponse(
                    reply="목록의 id를 선택해 주세요.\n" + format_entries(pending_selection["candidates"]),
                    pending_confirm=None,
                )

            if pending_selection["action"] == "update":
                updated = update_entry_amount(
                    app.state.db_path, entry_id, pending_selection["amount"]
                )
                app.state.pending_selection = None
                if not updated:
                    return ChatResponse(reply="수정에 실패했어요.", pending_confirm=None)
                return ChatResponse(
                    reply=f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원",
                    pending_confirm=None,
                )

            if pending_selection["action"] == "delete":
                token = uuid.uuid4().hex
                app.state.pending_selection = None
                app.state.pending_actions[token] = {
                    "token": token,
                    "action": "delete",
                    "entry_id": entry_id,
                }
                return ChatResponse(
                    reply=f"삭제할까요? {candidate['date']} {candidate['item']} {candidate['amount']}원",
                    pending_confirm=PendingConfirm(token=token, prompt="삭제 확인"),
                )

        result = app.state.graph.invoke({"message": payload.message})
        pending_confirm = None
        if result.get("pending_selection"):
            app.state.pending_selection = result["pending_selection"]
        if result.get("pending_action"):
            action = result["pending_action"]
            app.state.pending_actions[action["token"]] = action
            pending_confirm = PendingConfirm(**result["pending_confirm"])

        return ChatResponse(reply=result.get("reply", ""), pending_confirm=pending_confirm)

    @app.post("/confirm", response_model=ChatResponse)
    def confirm(payload: ConfirmRequest) -> ChatResponse:
        action = app.state.pending_actions.pop(payload.token, None)
        if not action:
            return ChatResponse(reply="확인할 항목이 없어요.", pending_confirm=None)

        if payload.decision == "no":
            return ChatResponse(reply="취소했어요.", pending_confirm=None)

        if action["action"] == "delete":
            deleted = delete_entry(app.state.db_path, action["entry_id"])
            if deleted:
                return ChatResponse(reply="삭제했어요.", pending_confirm=None)
            return ChatResponse(reply="삭제에 실패했어요.", pending_confirm=None)

        return ChatResponse(reply="처리할 수 없는 요청이에요.", pending_confirm=None)

    return app


app = create_app()
