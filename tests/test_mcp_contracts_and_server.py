from __future__ import annotations

import pytest

from server.mcp.ledger_server import LedgerMCPServer
from shared.mcp_contracts import normalize_tool_result, read_tool_input_schema, tool_arguments_for_call


def test_mcp_server_execute_roundtrip(tmp_path):
    db_path = str(tmp_path / "ledger.db")
    server = LedgerMCPServer(default_db_path=db_path)

    inserted = server.execute(
        "insert_ledger_entry",
        {"entry_date": "2026-02-12", "item": "당근", "amount": 4000},
        db_path=None,
    )
    assert inserted["item"] == "당근"
    assert inserted["amount"] == 4000

    rows = server.execute("list_ledger_entries", {"entry_date": "2026-02-12", "limit": 10}, db_path=None)
    assert len(rows) == 1
    assert rows[0]["item"] == "당근"

    total = server.execute("sum_ledger_entries", {"entry_date": "2026-02-12"}, db_path=None)
    assert total == 4000


def test_mcp_server_read_tool_schemas_contains_read_tools():
    server = LedgerMCPServer()
    schemas = server.get_read_tool_schemas()
    names = {schema["function"]["name"] for schema in schemas}
    assert names == {"list_ledger_entries", "sum_ledger_entries", "get_last_ledger_entry"}
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["type"] == "object"


def test_tool_arguments_for_call_parses_json_and_validates():
    args = tool_arguments_for_call("sum_ledger_entries", '{"entry_date":"2026-02-10"}')
    assert args["entry_date"] == "2026-02-10"

    with pytest.raises(Exception):
        tool_arguments_for_call("update_ledger_entry_amount", {"entry_id": "oops", "new_amount": 1000})


def test_normalize_tool_result_requires_list_for_list_tool():
    with pytest.raises(ValueError):
        normalize_tool_result("list_ledger_entries", {"id": 1})


def test_read_tool_input_schema_contains_known_fields():
    list_schema = read_tool_input_schema("list_ledger_entries")
    assert "entry_date" in list_schema["properties"]
    assert "limit" in list_schema["properties"]

    sum_schema = read_tool_input_schema("sum_ledger_entries")
    assert "entry_date" in sum_schema["properties"]


def test_mcp_server_execute_raises_for_unsupported_tool():
    server = LedgerMCPServer()
    with pytest.raises(ValueError):
        server.execute("unsupported_tool", {}, db_path=None)
