from __future__ import annotations

from shared.mcp_contracts import read_tool_input_schema


def _function_schema(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": read_tool_input_schema(name),
        },
    }


READ_TOOL_SCHEMAS = [
    _function_schema(
        "list_ledger_entries",
        "List ledger entries by date (or latest entries when date is empty).",
    ),
    _function_schema(
        "sum_ledger_entries",
        "Return total spend amount for a date or for all entries.",
    ),
    _function_schema(
        "get_last_ledger_entry",
        "Return the latest ledger entry.",
    ),
]
