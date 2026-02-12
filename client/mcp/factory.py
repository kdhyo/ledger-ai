from __future__ import annotations

import os
from typing import Optional

from .ledger_client import LedgerMCPClient
from .remote_client import RemoteLedgerMCPClient


def build_mcp_client(db_path: Optional[str]):
    mode = os.getenv("MCP_CLIENT_MODE", "local").strip().lower()
    if mode == "remote":
        base_url = os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8100/mcp")
        timeout = float(os.getenv("MCP_SERVER_TIMEOUT", "5"))
        return RemoteLedgerMCPClient(server_url=base_url, db_path=db_path, timeout=timeout)
    return LedgerMCPClient(db_path=db_path)
