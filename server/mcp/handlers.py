from __future__ import annotations

import logging
from typing import Any, Optional

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

    def get_read_tool_schemas(self) -> list[dict]:
        return READ_TOOL_SCHEMAS

    def execute(self, name: str, arguments: Any, db_path: Optional[str]):
        args = tool_arguments_for_call(name, arguments)
        resolved_db_path = db_path or self.default_db_path
        logger.info("mcp_server.execute.start tool=%s db_path=%s args=%s", name, resolved_db_path, args)

        if name == "insert_ledger_entry":
            result = insert_entry(
                resolved_db_path,
                args["entry_date"],
                args["item"],
                int(args["amount"]),
                args.get("note"),
            )
            logger.info("mcp_server.execute.done tool=%s result_type=%s", name, type(result).__name__)
            return result
        if name == "list_ledger_entries":
            result = list_entries(
                resolved_db_path,
                entry_date=args.get("entry_date"),
                limit=int(args.get("limit", 10)),
            )
            logger.info("mcp_server.execute.done tool=%s rows=%s", name, len(result))
            return result
        if name == "sum_ledger_entries":
            result = sum_entries(resolved_db_path, entry_date=args.get("entry_date"))
            logger.info("mcp_server.execute.done tool=%s sum=%s", name, result)
            return result
        if name == "get_last_ledger_entry":
            result = get_last_entry(resolved_db_path)
            logger.info("mcp_server.execute.done tool=%s found=%s", name, bool(result))
            return result
        if name == "update_ledger_entry_amount":
            result = update_entry_amount(
                resolved_db_path,
                int(args["entry_id"]),
                int(args["new_amount"]),
            )
            logger.info("mcp_server.execute.done tool=%s updated=%s", name, bool(result))
            return result
        if name == "delete_ledger_entry":
            result = delete_entry(resolved_db_path, int(args["entry_id"]))
            logger.info("mcp_server.execute.done tool=%s deleted=%s", name, result)
            return result
        if name == "get_read_resource_context":
            result = build_read_resource_context(
                resolved_db_path,
                entry_date=args.get("entry_date"),
                limit=int(args.get("limit", 5)),
            )
            logger.info("mcp_server.execute.done tool=%s chars=%s", name, len(result))
            return result

        logger.warning("mcp_server.execute.unsupported tool=%s", name)
        raise ValueError(f"Unsupported MCP tool: {name}")
