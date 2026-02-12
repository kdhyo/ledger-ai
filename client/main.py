from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .graph import build_graph, load_prompt
from .llm import get_llm
from .session_state import SessionStateStore
from .schemas import ChatRequest, ChatResponse, ConfirmRequest, PendingConfirm

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def create_app(db_path: Optional[str] = None, use_fake_llm: bool = False) -> FastAPI:
    app = FastAPI()
    root_dir = Path(__file__).resolve().parents[1]
    static_dir = root_dir / "client" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.state.db_path = db_path
    app.state.session_store = SessionStateStore()
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
        session_id = payload.session_id or "default"
        logger.info("client.chat.request session_id=%s message=%s", session_id, payload.message)
        session_state = app.state.session_store.get(session_id)
        result = app.state.graph.invoke(
            {
                "message": payload.message,
                "pending_confirm": session_state.pending_confirm,
                "pending_action": session_state.pending_action,
                "pending_selection": session_state.pending_selection,
            }
        )

        updated = app.state.session_store.update_from_result(session_id, result)

        pending_confirm = (
            PendingConfirm(**updated.pending_confirm)
            if updated.pending_confirm
            else None
        )
        logger.info(
            "client.chat.response reply=%s pending_confirm=%s",
            result.get("reply", ""),
            bool(pending_confirm),
        )
        return ChatResponse(reply=result.get("reply", ""), pending_confirm=pending_confirm)

    @app.post("/confirm", response_model=ChatResponse)
    def confirm(payload: ConfirmRequest) -> ChatResponse:
        session_id = payload.session_id or "default"
        logger.info(
            "client.confirm.request session_id=%s token=%s decision=%s",
            session_id,
            payload.token,
            payload.decision,
        )
        session_state = app.state.session_store.get(session_id)
        current_confirm = session_state.pending_confirm
        if not current_confirm:
            return ChatResponse(reply="확인할 항목이 없어요.", pending_confirm=None)

        if payload.token != current_confirm.get("token"):
            return ChatResponse(
                reply="확인 토큰이 유효하지 않아요.",
                pending_confirm=PendingConfirm(**current_confirm),
            )

        result = app.state.graph.invoke(
            {
                "message": payload.decision,
                "pending_confirm": session_state.pending_confirm,
                "pending_action": session_state.pending_action,
                "pending_selection": session_state.pending_selection,
            }
        )

        updated = app.state.session_store.update_from_result(session_id, result)

        pending_confirm = (
            PendingConfirm(**updated.pending_confirm)
            if updated.pending_confirm
            else None
        )
        logger.info(
            "client.confirm.response reply=%s pending_confirm=%s",
            result.get("reply", ""),
            bool(pending_confirm),
        )
        return ChatResponse(reply=result.get("reply", ""), pending_confirm=pending_confirm)

    return app


configure_logging()
app = create_app()
