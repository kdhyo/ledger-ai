from __future__ import annotations

import os
from typing import Optional

from .remote_client import RemoteLedgerMCPClient


def build_mcp_client(db_path: Optional[str]):
    base_url = os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8100/mcp")
    timeout = float(os.getenv("MCP_SERVER_TIMEOUT", "5"))
    return RemoteLedgerMCPClient(server_url=base_url, db_path=db_path, timeout=timeout)
