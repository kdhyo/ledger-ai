from __future__ import annotations

from client.graph_nodes import LedgerGraphNodes
from client.llm import FakeLLM


def _new_nodes():
    return LedgerGraphNodes(db_path=None, llm=FakeLLM(), prompt="today is {today}")


def test_run_select_handles_tool_error(monkeypatch):
    nodes = _new_nodes()

    monkeypatch.setattr(nodes, "_invoke_tool", lambda tool_obj, payload, **kwargs: None)

    out = nodes.run_select_node({"intent_date": "2026-02-10"})

    assert "오류" in out["reply"]
    assert out["pending_confirm"] is None
    assert out["pending_action"] is None
    assert out["pending_selection"] is None


def test_confirm_delete_handles_tool_error(monkeypatch):
    nodes = _new_nodes()

    monkeypatch.setattr(nodes, "_invoke_tool", lambda tool_obj, payload, **kwargs: kwargs.get("default"))

    out = nodes.confirm_decision_node(
        {
            "message": "yes",
            "pending_confirm": {"token": "t", "prompt": "삭제 확인"},
            "pending_action": {"token": "t", "action": "delete", "entry_id": 1},
        }
    )

    assert "오류" in out["reply"]
    assert out["pending_confirm"] is None
    assert out["pending_action"] is None
    assert out["pending_selection"] is None
