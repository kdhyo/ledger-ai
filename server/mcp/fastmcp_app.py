from __future__ import annotations

from typing import Any, Optional

from server.graph_resources import get_ledger_schema_resource

from .handlers import LedgerMCPServer

try:
    from fastmcp import FastMCP
except Exception:  # pragma: no cover - optional dependency at runtime
    FastMCP = None


def create_fastmcp_server(default_db_path: Optional[str]) -> Any:
    if FastMCP is None:
        raise RuntimeError("fastmcp is not installed")

    server = LedgerMCPServer(default_db_path=default_db_path)
    mcp = FastMCP("ledger-mcp-server")

    def _db_path(db_path: Optional[str]) -> Optional[str]:
        return db_path or default_db_path

    @mcp.tool(name="insert_ledger_entry")
    def insert_ledger_entry(
        entry_date: str,
        item: str,
        amount: int,
        note: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> dict:
        return server.execute(
            "insert_ledger_entry",
            {"entry_date": entry_date, "item": item, "amount": amount, "note": note},
            _db_path(db_path),
        )

    @mcp.tool(name="list_ledger_entries")
    def list_ledger_entries(
        entry_date: Optional[str] = None,
        limit: int = 10,
        db_path: Optional[str] = None,
    ) -> list[dict]:
        return server.execute(
            "list_ledger_entries",
            {"entry_date": entry_date, "limit": limit},
            _db_path(db_path),
        )

    @mcp.tool(name="sum_ledger_entries")
    def sum_ledger_entries(entry_date: Optional[str] = None, db_path: Optional[str] = None) -> int:
        return server.execute(
            "sum_ledger_entries",
            {"entry_date": entry_date},
            _db_path(db_path),
        )

    @mcp.tool(name="get_last_ledger_entry")
    def get_last_ledger_entry(db_path: Optional[str] = None) -> Optional[dict]:
        return server.execute("get_last_ledger_entry", {}, _db_path(db_path))

    @mcp.tool(name="update_ledger_entry_amount")
    def update_ledger_entry_amount(
        entry_id: int,
        new_amount: int,
        db_path: Optional[str] = None,
    ) -> Optional[dict]:
        return server.execute(
            "update_ledger_entry_amount",
            {"entry_id": entry_id, "new_amount": new_amount},
            _db_path(db_path),
        )

    @mcp.tool(name="delete_ledger_entry")
    def delete_ledger_entry(entry_id: int, db_path: Optional[str] = None) -> bool:
        return server.execute(
            "delete_ledger_entry",
            {"entry_id": entry_id},
            _db_path(db_path),
        )

    @mcp.tool(name="get_read_resource_context")
    def get_read_resource_context(
        entry_date: Optional[str] = None,
        limit: int = 5,
        db_path: Optional[str] = None,
    ) -> str:
        return server.execute(
            "get_read_resource_context",
            {"entry_date": entry_date, "limit": limit},
            _db_path(db_path),
        )

    @mcp.resource("ledger://schema")
    def ledger_schema_resource() -> str:
        return get_ledger_schema_resource()

    @mcp.prompt(name="read_tool_system_prompt")
    def read_tool_system_prompt(resource_context: str) -> str:
        context = resource_context.strip() or "(none)"
        return (
            "You are a read-only ledger assistant. "
            "Use exactly one available read tool for each query. "
            "Never call write/update/delete tools.\n\n"
            f"Context resources:\n{context}"
        )

    return mcp
