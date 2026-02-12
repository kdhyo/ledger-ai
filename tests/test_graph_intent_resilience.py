from __future__ import annotations

from client import graph_intent as gi
from client.graph_state import Intent
from client.llm import FakeLLM


def test_bulk_insert_falls_back_to_segment_extract_on_batch_error(monkeypatch):
    def broken_batch(messages, llm, prompt):
        raise RuntimeError("batch failed")

    def fake_extract(message, llm, prompt):
        if "당근" in message:
            return Intent(intent="insert", date=None, item="당근", amount=4000, target=None)
        if "양상추" in message:
            return Intent(intent="insert", date=None, item="양상추", amount=3000, target=None)
        return Intent(intent="unknown", date=None, item=None, amount=None, target=None)

    monkeypatch.setattr(gi, "_batch_invoke_intent_chain", broken_batch)
    monkeypatch.setattr(gi, "extract_intent", fake_extract)

    candidates = gi.extract_bulk_insert_candidates(
        "오늘 당근 4000원, 양상추 3000원 샀어",
        None,
        FakeLLM(),
        "prompt",
    )

    assert len(candidates) == 2
    assert candidates[0]["item"] == "당근"
    assert candidates[1]["item"] == "양상추"


def test_intent_chain_cache_is_bounded_per_llm():
    llm = FakeLLM()

    for i in range(12):
        gi._get_intent_chain(llm, f"prompt-{i}")

    llm_cache = gi._INTENT_CHAIN_CACHE.get(llm)
    assert llm_cache is not None
    assert len(llm_cache) <= gi._MAX_PROMPT_CHAINS_PER_LLM


def test_extract_intent_uses_parser_fallback_for_json_snippet(monkeypatch):
    snippet = (
        'answer: {"intent":"sum","date":"2026-02-10",'
        '"item":null,"amount":null,"target":null}'
    )

    monkeypatch.setattr(gi, "_invoke_intent_chain", lambda message, llm, prompt: snippet)

    parsed = gi.extract_intent("합계", FakeLLM(), "prompt")

    assert parsed.intent == "sum"
    assert parsed.date == "2026-02-10"
