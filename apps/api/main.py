from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .graph import build_graph, load_prompt
from .llm import get_llm
from .schemas import ChatRequest, ChatResponse, ConfirmRequest, PendingConfirm


def create_app(db_path: Optional[str] = None, use_fake_llm: bool = False) -> FastAPI:
    app = FastAPI()
    root_dir = Path(__file__).resolve().parents[2]
    static_dir = root_dir / "apps" / "api" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.state.db_path = db_path
    app.state.pending_action = None
    app.state.pending_confirm = None
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
        result = app.state.graph.invoke(
            {
                "message": payload.message,
                "pending_confirm": app.state.pending_confirm,
                "pending_action": app.state.pending_action,
                "pending_selection": app.state.pending_selection,
            }
        )

        app.state.pending_confirm = result.get("pending_confirm")
        app.state.pending_action = result.get("pending_action")
        app.state.pending_selection = result.get("pending_selection")

        pending_confirm = (
            PendingConfirm(**app.state.pending_confirm)
            if app.state.pending_confirm
            else None
        )
        return ChatResponse(reply=result.get("reply", ""), pending_confirm=pending_confirm)

    @app.post("/confirm", response_model=ChatResponse)
    def confirm(payload: ConfirmRequest) -> ChatResponse:
        current_confirm = app.state.pending_confirm
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
                "pending_confirm": app.state.pending_confirm,
                "pending_action": app.state.pending_action,
                "pending_selection": app.state.pending_selection,
            }
        )

        app.state.pending_confirm = result.get("pending_confirm")
        app.state.pending_action = result.get("pending_action")
        app.state.pending_selection = result.get("pending_selection")

        pending_confirm = (
            PendingConfirm(**app.state.pending_confirm)
            if app.state.pending_confirm
            else None
        )
        return ChatResponse(reply=result.get("reply", ""), pending_confirm=pending_confirm)

    return app


app = create_app()
