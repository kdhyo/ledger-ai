from __future__ import annotations

from typing import Optional

from langgraph.graph import END, StateGraph

from .graph_nodes import LedgerGraphNodes
from .graph_state import ChatState
from .llm import FakeLLM, OllamaLLM


def build_graph(db_path: Optional[str], llm: OllamaLLM | FakeLLM, prompt: str):
    nodes = LedgerGraphNodes(db_path=db_path, llm=llm, prompt=prompt)

    builder = StateGraph(ChatState)
    builder.add_node("entry", nodes.entry_node)
    builder.add_node("empty_message", nodes.empty_message_node)
    builder.add_node("confirm_decision", nodes.confirm_decision_node)
    builder.add_node("selection_decision", nodes.selection_decision_node)
    builder.add_node("extract_intent", nodes.extract_intent_node)
    builder.add_node("run_insert", nodes.run_insert_node)
    builder.add_node("run_select", nodes.run_select_node)
    builder.add_node("run_sum", nodes.run_sum_node)
    builder.add_node("run_update_prepare", nodes.run_update_prepare_node)
    builder.add_node("run_delete_prepare", nodes.run_delete_prepare_node)
    builder.add_node("run_unknown", nodes.run_unknown_node)

    builder.set_entry_point("entry")
    builder.add_conditional_edges(
        "entry",
        nodes.route_from_entry,
        {
            "empty": "empty_message",
            "confirm": "confirm_decision",
            "selection": "selection_decision",
            "extract": "extract_intent",
        },
    )
    builder.add_conditional_edges(
        "extract_intent",
        nodes.route_intent,
        {
            "insert": "run_insert",
            "select": "run_select",
            "sum": "run_sum",
            "update": "run_update_prepare",
            "delete": "run_delete_prepare",
            "unknown": "run_unknown",
        },
    )

    builder.add_edge("empty_message", END)
    builder.add_edge("confirm_decision", END)
    builder.add_edge("selection_decision", END)
    builder.add_edge("run_insert", END)
    builder.add_edge("run_select", END)
    builder.add_edge("run_sum", END)
    builder.add_edge("run_update_prepare", END)
    builder.add_edge("run_delete_prepare", END)
    builder.add_edge("run_unknown", END)

    return builder.compile()
