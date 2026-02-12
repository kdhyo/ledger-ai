from __future__ import annotations

import logging
from typing import Any, Optional

from shared.mcp_contracts import normalize_tool_result

from server.graph_resources import build_read_resource_context
from server.mcp.ledger_server import LedgerMCPServer

logger = logging.getLogger(__name__)


class LedgerMCPClient:
    def __init__(self, db_path: Optional[str], server: Optional[LedgerMCPServer] = None) -> None:
        self.db_path = db_path
        self.server = server or LedgerMCPServer()

    def get_read_tool_schemas(self) -> list[dict]:
        logger.info("mcp_client(local).list_tools")
        return self.server.get_read_tool_schemas()

    def get_read_resource_context(self, entry_date: Optional[str], limit: int = 5) -> str:
        logger.info("mcp_client(local).read_resource entry_date=%s limit=%s", entry_date, limit)
        return build_read_resource_context(self.db_path, entry_date=entry_date, limit=limit)

    def invoke(self, name: str, arguments: Any):
        logger.info("mcp_client(local).invoke tool=%s args=%s", name, arguments)
        result = self.server.execute(name, arguments, self.db_path)
        result = normalize_tool_result(name, result)
        logger.info("mcp_client(local).invoke.done tool=%s result_type=%s", name, type(result).__name__)
        return result
