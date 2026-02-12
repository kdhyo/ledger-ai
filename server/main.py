from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from server.mcp.ledger_server import create_fastmcp_server


def _default_db_path() -> str:
    root_dir = Path(__file__).resolve().parents[1]
    return str(root_dir / "ledger.db")


def build_mcp() -> Any:
    return create_fastmcp_server(default_db_path=_default_db_path())


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    mcp = build_mcp()
    host = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_SERVER_PORT", "8100"))
    path = os.getenv("MCP_SERVER_PATH", "/mcp")
    logging.getLogger(__name__).info(
        "server.start host=%s port=%s path=%s",
        host,
        port,
        path,
    )

    # FastMCP runtime is provided by the SDK.
    mcp.run(transport="streamable-http", host=host, port=port, path=path)


if __name__ == "__main__":
    run()
