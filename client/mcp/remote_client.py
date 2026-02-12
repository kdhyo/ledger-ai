from __future__ import annotations

import asyncio
import atexit
import json
import logging
import uuid
from threading import Thread
from typing import Any, Optional

from shared.mcp_contracts import normalize_tool_result, tool_arguments_for_call

logger = logging.getLogger(__name__)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _to_jsonable(value.dict())
    if hasattr(value, "text"):
        return value.text
    return str(value)


def _extract_tool_result(result: Any) -> Any:
    if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
        return result

    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    return _to_jsonable(result)


class _AsyncLoopRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, name="mcp-client-loop", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self) -> None:
        if not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1.0)


class RemoteLedgerMCPClient:
    def __init__(self, server_url: str, db_path: Optional[str], timeout: float = 10.0) -> None:
        self.server_url = server_url
        self.db_path = db_path
        self.timeout = timeout
        self._runner = _AsyncLoopRunner()

    def _run(self, coro):
        return self._runner.run(coro)

    async def _with_client(self, callback):
        try:
            from fastmcp import Client
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("fastmcp is not installed") from exc

        async with Client(self.server_url, timeout=self.timeout) as client:
            return await callback(client)

    def get_read_tool_schemas(self) -> list[dict]:
        request_id = uuid.uuid4().hex[:8]
        logger.info("mcp_client.list_tools.start request_id=%s server_url=%s", request_id, self.server_url)

        async def op(client):
            tools = await client.list_tools()
            schemas = []
            for tool in tools:
                name = getattr(tool, "name", None)
                if name not in {"list_ledger_entries", "sum_ledger_entries", "get_last_ledger_entry"}:
                    continue
                description = getattr(tool, "description", "")
                input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {
                    "type": "object",
                    "properties": {},
                    "required": [],
                }
                schemas.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": description,
                            "parameters": _to_jsonable(input_schema),
                        },
                    }
                )
            return schemas

        schemas = self._run(self._with_client(op))
        logger.info(
            "mcp_client.list_tools.done request_id=%s tools=%d",
            request_id,
            len(schemas),
        )
        return schemas

    def get_read_resource_context(self, entry_date: Optional[str], limit: int = 5) -> str:
        logger.info("mcp_client.read_resource request entry_date=%s limit=%s", entry_date, limit)
        args = {"entry_date": entry_date, "limit": limit, "db_path": self.db_path}
        result = self.invoke("get_read_resource_context", args)
        return result if isinstance(result, str) else str(result)

    def invoke(self, name: str, arguments: Any):
        request_id = uuid.uuid4().hex[:8]
        args = tool_arguments_for_call(name, arguments)
        if self.db_path and "db_path" not in args:
            args = {**args, "db_path": self.db_path}
        logger.info(
            "mcp_client.invoke.start request_id=%s tool=%s args=%s",
            request_id,
            name,
            args,
        )

        async def op(client):
            result = await client.call_tool(name, args)
            extracted = _extract_tool_result(result)
            return normalize_tool_result(name, extracted)

        result = self._run(self._with_client(op))
        logger.info(
            "mcp_client.invoke.done request_id=%s tool=%s result_type=%s",
            request_id,
            name,
            type(result).__name__,
        )
        return result
