from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import date as date_module, timedelta
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict
from weakref import WeakKeyDictionary

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from .graph_prompts import render_intent_chain_prompt
from .graph_state import Intent
from .llm import FakeLLM, OllamaLLM
from shared.time_utils import today_iso


class IntentExtraction(BaseModel):
    intent: Literal["insert", "select", "update", "delete", "sum", "unknown"] = "unknown"
    date: Optional[str] = None
    item: Optional[str] = None
    amount: Optional[int] = Field(default=None)
    target: Optional[Literal["last"]] = None


class _IntentInput(TypedDict):
    message: str


class _IntentPayload(TypedDict):
    system_prompt: str
    message: str


INTENT_OUTPUT_PARSER = PydanticOutputParser(pydantic_object=IntentExtraction)
_INTENT_CHAIN_CACHE: WeakKeyDictionary[object, OrderedDict[str, Any]] = WeakKeyDictionary()
_MAX_PROMPT_CHAINS_PER_LLM = 8


def load_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "intent_extract.md"
    return prompt_path.read_text(encoding="utf-8")


def parse_intent_from_llm(output: str) -> Optional[dict]:
    if not output:
        return None

    text = output.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_intent_chain(llm: OllamaLLM | FakeLLM, prompt: str):
    system_prompt = render_intent_chain_prompt(
        base_prompt=prompt,
        format_instructions=INTENT_OUTPUT_PARSER.get_format_instructions(),
    )

    def to_payload(data: _IntentInput) -> _IntentPayload:
        return {"system_prompt": system_prompt, "message": data["message"]}

    def call_llm(data: _IntentPayload) -> str:
        return llm.chat(data["system_prompt"], data["message"])

    return RunnableLambda(to_payload) | RunnableLambda(call_llm)


def _get_intent_chain(llm: OllamaLLM | FakeLLM, prompt: str):
    global _INTENT_CHAIN_CACHE
    if not isinstance(_INTENT_CHAIN_CACHE, WeakKeyDictionary):
        _INTENT_CHAIN_CACHE = WeakKeyDictionary()

    llm_cache = _INTENT_CHAIN_CACHE.get(llm)
    if llm_cache is None:
        llm_cache = OrderedDict()
        _INTENT_CHAIN_CACHE[llm] = llm_cache

    cached = llm_cache.get(prompt)
    if cached is not None:
        llm_cache.move_to_end(prompt)
        return cached

    cached = _build_intent_chain(llm, prompt)
    llm_cache[prompt] = cached
    if len(llm_cache) > _MAX_PROMPT_CHAINS_PER_LLM:
        llm_cache.popitem(last=False)
    return cached


def _invoke_intent_chain(message: str, llm: OllamaLLM | FakeLLM, prompt: str) -> str:
    chain = _get_intent_chain(llm, prompt)
    result = chain.invoke({"message": message})
    return result if isinstance(result, str) else ""


def _batch_invoke_intent_chain(messages: list[str], llm: OllamaLLM | FakeLLM, prompt: str) -> list[str]:
    chain = _get_intent_chain(llm, prompt)
    results = chain.batch([{"message": message} for message in messages])
    out = []
    for result in results:
        out.append(result if isinstance(result, str) else "")
    return out


def _parse_intent_output(output: str) -> Optional[IntentExtraction]:
    if not output:
        return None

    try:
        return INTENT_OUTPUT_PARSER.parse(output)
    except Exception:
        parsed = parse_intent_from_llm(output)
        if isinstance(parsed, dict):
            try:
                return IntentExtraction.model_validate(parsed)
            except Exception:
                return None
    return None


def normalize_relative_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    value = str(text).strip().lower()

    if value in {"today", "오늘"}:
        return today_iso()
    if value in {"yesterday", "어제"}:
        return (date_module.today() - timedelta(days=1)).isoformat()
    if value in {"day before yesterday", "2 days ago", "two days ago", "그제", "엊그제"}:
        return (date_module.today() - timedelta(days=2)).isoformat()

    m = re.search(r"(\d+)\s*days?\s*ago", value)
    if m:
        return (date_module.today() - timedelta(days=int(m.group(1)))).isoformat()

    m = re.search(r"(\d+)\s*일\s*전", value)
    if m:
        return (date_module.today() - timedelta(days=int(m.group(1)))).isoformat()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value

    m = re.fullmatch(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", value)
    if m:
        year = date_module.today().year
        month = int(m.group(1))
        day = int(m.group(2))
        try:
            return date_module(year, month, day).isoformat()
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{1,2})\s*일", value)
    if m:
        today = date_module.today()
        day = int(m.group(1))
        try:
            return date_module(today.year, today.month, day).isoformat()
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{2,4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", value)
    if m:
        year_raw = int(m.group(1))
        year = 2000 + year_raw if year_raw < 100 else year_raw
        month = int(m.group(2))
        day = int(m.group(3))
        try:
            return date_module(year, month, day).isoformat()
        except ValueError:
            return None

    return None


def normalize_amount(value) -> Optional[int]:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9]", "", str(value))
    if not cleaned:
        return None
    return int(cleaned)


def is_item_substring(message: str, item: Optional[str]) -> bool:
    if not item:
        return False
    msg = (message or "").strip()
    it = item.strip()
    if not msg or not it:
        return False
    return it in msg or re.sub(r"\s+", "", it) in re.sub(r"\s+", "", msg)


def extract_date_from_message(message: str) -> Optional[str]:
    msg = message or ""
    date_patterns = [
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{2,4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일",
        r"\d{1,2}\s*월\s*\d{1,2}\s*일",
        r"\d{1,2}\s*일(?!\s*전)",
        r"\d+\s*일\s*전",
        r"\d+\s*days?\s*ago",
    ]
    for pat in date_patterns:
        m_date = re.search(pat, msg, re.I)
        if m_date:
            normalized = normalize_relative_date(m_date.group(0))
            if normalized:
                return normalized

    msg_l = msg.lower()
    if "오늘" in msg or "today" in msg_l:
        return today_iso()
    if "어제" in msg or "yesterday" in msg_l:
        return (date_module.today() - timedelta(days=1)).isoformat()
    return None


def minimal_fallback_intent(message: str) -> Intent:
    msg = message or ""
    msg_l = msg.lower()

    intent = "unknown"
    if "총합" in msg or "합계" in msg or "sum" in msg_l or "total" in msg_l:
        intent = "sum"
    elif "삭제" in msg or "지워" in msg or "delete" in msg_l:
        intent = "delete"
    elif "수정" in msg or "바꿔" in msg or "change" in msg_l or "update" in msg_l:
        intent = "update"
    elif "내역" in msg or "조회" in msg or "뭐" in msg or "what did i" in msg_l or "list" in msg_l:
        intent = "select"
    elif re.search(r"([\d,]+)\s*원", msg) or re.search(r"\b\d+\b", msg_l):
        intent = "insert"

    target = None
    if any(k in msg for k in ["방금", "최근", "그거", "그것", "마지막"]) or "last" in msg_l:
        target = "last"

    entry_date = extract_date_from_message(msg)

    amount = None
    m = re.search(r"([\d,]+)\s*원", msg)
    if m:
        amount = normalize_amount(m.group(1))

    return Intent(intent=intent, date=entry_date, item=None, amount=amount, target=target)


def extract_intent(message: str, llm: OllamaLLM | FakeLLM, prompt: str) -> Intent:
    data = {}
    try:
        output = _invoke_intent_chain(message, llm, prompt)
        parsed = _parse_intent_output(output)
        if parsed:
            data = parsed.model_dump()
    except Exception:
        data = {}

    if not data or "intent" not in data:
        return minimal_fallback_intent(message)

    intent = str(data.get("intent", "unknown")).strip().lower()
    if intent not in {"insert", "select", "update", "delete", "sum", "unknown"}:
        intent = "unknown"

    if intent == "unknown":
        fallback = minimal_fallback_intent(message)
        if fallback.intent != "unknown":
            return fallback

    date_value = normalize_relative_date(data.get("date")) if data.get("date") else None

    item_value = data.get("item")
    item = str(item_value).strip() if item_value else None
    if item and not is_item_substring(message, item):
        item = None

    amount = normalize_amount(data.get("amount")) if data.get("amount") is not None else None

    target = data.get("target")
    target = str(target).strip() if target else None
    if target not in {None, "last"}:
        target = None

    return Intent(intent=intent, date=date_value, item=item, amount=amount, target=target)


def extract_bulk_insert_candidates(
    message: str,
    entry_date: Optional[str],
    llm: OllamaLLM | FakeLLM,
    prompt: str,
) -> list[dict]:
    msg = message or ""
    if "원" not in msg or "," not in msg:
        return []

    default_date = extract_date_from_message(msg) or entry_date or today_iso()
    segments = [segment.strip() for segment in re.split(r"\s*,\s*", msg) if segment.strip()]
    if len(segments) < 2:
        return []

    parsed_segments: list[Intent] = []
    try:
        outputs = _batch_invoke_intent_chain(segments, llm, prompt)
        for idx, output in enumerate(outputs):
            parsed = _parse_intent_output(output)
            if not parsed:
                parsed_segments.append(extract_intent(segments[idx], llm, prompt))
                continue
            data = parsed.model_dump()
            parsed_segments.append(
                Intent(
                    intent=str(data.get("intent", "unknown")),
                    date=normalize_relative_date(data.get("date")) if data.get("date") else None,
                    item=str(data.get("item")).strip() if data.get("item") else None,
                    amount=normalize_amount(data.get("amount")) if data.get("amount") is not None else None,
                    target=str(data.get("target")).strip() if data.get("target") else None,
                )
            )
    except Exception:
        parsed_segments = [extract_intent(segment, llm, prompt) for segment in segments]

    candidates = []
    for parsed in parsed_segments:
        if parsed.intent != "insert" or not parsed.item or parsed.amount is None:
            continue
        candidates.append({
            "date": parsed.date or default_date,
            "item": parsed.item,
            "amount": parsed.amount,
        })
    return candidates
