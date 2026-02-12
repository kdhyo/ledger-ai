from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class _BaseArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")


class InsertLedgerEntryArgs(_BaseArgs):
    entry_date: str
    item: str
    amount: int
    note: Optional[str] = None


class ListLedgerEntriesArgs(_BaseArgs):
    entry_date: Optional[str] = None
    limit: int = 10


class SumLedgerEntriesArgs(_BaseArgs):
    entry_date: Optional[str] = None


class GetLastLedgerEntryArgs(_BaseArgs):
    pass


class UpdateLedgerEntryAmountArgs(_BaseArgs):
    entry_id: int
    new_amount: int


class DeleteLedgerEntryArgs(_BaseArgs):
    entry_id: int


class ReadResourceContextArgs(_BaseArgs):
    entry_date: Optional[str] = None
    limit: int = 5


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    date: str
    item: str
    amount: int
    note: Optional[str] = None
    created_at: Optional[str] = None


_ARG_MODEL_BY_TOOL: dict[str, type[_BaseArgs]] = {
    "insert_ledger_entry": InsertLedgerEntryArgs,
    "list_ledger_entries": ListLedgerEntriesArgs,
    "sum_ledger_entries": SumLedgerEntriesArgs,
    "get_last_ledger_entry": GetLastLedgerEntryArgs,
    "update_ledger_entry_amount": UpdateLedgerEntryAmountArgs,
    "delete_ledger_entry": DeleteLedgerEntryArgs,
    "get_read_resource_context": ReadResourceContextArgs,
}


def coerce_arguments(arguments: Any) -> dict:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def tool_arguments_for_call(tool_name: str, arguments: Any) -> dict:
    model_cls = _ARG_MODEL_BY_TOOL.get(tool_name)
    coerced = coerce_arguments(arguments)
    if model_cls is None:
        return coerced
    validated = model_cls.model_validate(coerced)
    return validated.model_dump(exclude_none=True)


def read_tool_input_schema(tool_name: str) -> dict:
    model_cls = {
        "list_ledger_entries": ListLedgerEntriesArgs,
        "sum_ledger_entries": SumLedgerEntriesArgs,
        "get_last_ledger_entry": GetLastLedgerEntryArgs,
    }.get(tool_name)
    if model_cls is None:
        raise ValueError(f"Unsupported read tool: {tool_name}")
    return model_cls.model_json_schema()


def normalize_tool_result(tool_name: str, value: Any) -> Any:
    if tool_name in {"insert_ledger_entry", "update_ledger_entry_amount"}:
        return LedgerEntry.model_validate(value).model_dump()
    if tool_name == "list_ledger_entries":
        if not isinstance(value, list):
            raise ValueError("list_ledger_entries result must be a list")
        return [LedgerEntry.model_validate(row).model_dump() for row in value]
    if tool_name == "sum_ledger_entries":
        return int(value)
    if tool_name == "get_last_ledger_entry":
        if value is None:
            return None
        return LedgerEntry.model_validate(value).model_dump()
    if tool_name == "delete_ledger_entry":
        return bool(value)
    if tool_name == "get_read_resource_context":
        return value if isinstance(value, str) else str(value)
    return value
