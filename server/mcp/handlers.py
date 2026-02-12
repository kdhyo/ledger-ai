from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from shared.mcp_contracts import tool_arguments_for_call

from server.graph_resources import build_read_resource_context
from server.tools.ledger_tools import (
    delete_entry,
    get_last_entry,
    insert_entry,
    list_entries,
    sum_entries,
    update_entry_amount,
)

from .schemas import READ_TOOL_SCHEMAS

logger = logging.getLogger(__name__)


class LedgerMCPServer:
    def __init__(self, default_db_path: Optional[str] = None) -> None:
        self.default_db_path = default_db_path
        self._handlers: dict[str, Callable[[dict, Optional[str]], Any]] = {
            "insert_ledger_entry": self._handle_insert_ledger_entry,
            "list_ledger_entries": self._handle_list_ledger_entries,
            "sum_ledger_entries": self._handle_sum_ledger_entries,
            "get_last_ledger_entry": self._handle_get_last_ledger_entry,
            "update_ledger_entry_amount": self._handle_update_ledger_entry_amount,
            "delete_ledger_entry": self._handle_delete_ledger_entry,
            "get_read_resource_context": self._handle_get_read_resource_context,
        }

    def get_read_tool_schemas(self) -> list[dict]:
        return READ_TOOL_SCHEMAS

    def _handle_insert_ledger_entry(self, args: dict, db_path: Optional[str]) -> dict:
        return insert_entry(
            db_path,
            args["entry_date"],
            args["item"],
            int(args["amount"]),
            args.get("note"),
        )

    def _handle_list_ledger_entries(self, args: dict, db_path: Optional[str]) -> list[dict]:
        return list_entries(
            db_path,
            entry_date=args.get("entry_date"),
            limit=int(args.get("limit", 10)),
        )

    def _handle_sum_ledger_entries(self, args: dict, db_path: Optional[str]) -> int:
        return sum_entries(db_path, entry_date=args.get("entry_date"))

    def _handle_get_last_ledger_entry(self, args: dict, db_path: Optional[str]) -> Optional[dict]:
        return get_last_entry(db_path)

    def _handle_update_ledger_entry_amount(self, args: dict, db_path: Optional[str]) -> Optional[dict]:
        return update_entry_amount(
            db_path,
            int(args["entry_id"]),
            int(args["new_amount"]),
        )

    def _handle_delete_ledger_entry(self, args: dict, db_path: Optional[str]) -> bool:
        return delete_entry(db_path, int(args["entry_id"]))

    def _handle_get_read_resource_context(self, args: dict, db_path: Optional[str]) -> str:
        return build_read_resource_context(
            db_path,
            entry_date=args.get("entry_date"),
            limit=int(args.get("limit", 5)),
        )

    def execute(self, name: str, arguments: Any, db_path: Optional[str]):
        handler = self._handlers.get(name)
        if handler is None:
            logger.warning("mcp_server.execute.unsupported tool=%s", name)
            raise ValueError(f"Unsupported MCP tool: {name}")

        args = tool_arguments_for_call(name, arguments)
        resolved_db_path = db_path or self.default_db_path
        logger.info("mcp_server.execute.start tool=%s db_path=%s args=%s", name, resolved_db_path, args)
        result = handler(args, resolved_db_path)
        logger.info("mcp_server.execute.done tool=%s result_type=%s", name, type(result).__name__)
        return result
