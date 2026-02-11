from __future__ import annotations

import json
import re
import uuid
from datetime import date as date_module, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from .llm import OllamaLLM, FakeLLM
from .tools.ledger_tools import (
    delete_entry,
    get_last_entry,
    insert_entry,
    list_entries,
    today_iso,
    update_entry_amount,
)


class ChatState(TypedDict, total=False):
    message: str
    reply: str
    pending_confirm: Optional[dict]      # {"token": "...", "prompt": "..."}
    pending_action: Optional[dict]       # {"token":"...","action":"delete","entry_id":"..."}
    pending_selection: Optional[dict]    # {"action":"update|delete","candidates":[...], ...}


@dataclass
class Intent:
    intent: str
    date: Optional[str] = None
    item: Optional[str] = None
    amount: Optional[int] = None
    target: Optional[str] = None


def load_prompt() -> str:
    prompt_path = Path(__file__).resolve().parents[2] / "prompts" / "intent_extract.md"
    return prompt_path.read_text(encoding="utf-8")


def parse_intent_from_llm(output: str) -> Optional[dict]:
    """
    With Ollama structured output, output should be JSON only.
    Still supports fallback extraction of a {...} block if the model leaks extra text.
    """
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


def normalize_relative_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    value = str(text).strip().lower()

    # English
    if value in {"today"}:
        return today_iso()
    if value in {"yesterday"}:
        return (date_module.today() - timedelta(days=1)).isoformat()
    if value in {"day before yesterday", "2 days ago", "two days ago"}:
        return (date_module.today() - timedelta(days=2)).isoformat()

    # Korean
    if value in {"오늘"}:
        return today_iso()
    if value in {"어제"}:
        return (date_module.today() - timedelta(days=1)).isoformat()
    if value in {"그제", "엊그제"}:
        return (date_module.today() - timedelta(days=2)).isoformat()

    # "N days ago" / "N일 전"
    m = re.search(r"(\d+)\s*days?\s*ago", value)
    if m:
        days = int(m.group(1))
        return (date_module.today() - timedelta(days=days)).isoformat()

    m = re.search(r"(\d+)\s*일\s*전", value)
    if m:
        days = int(m.group(1))
        return (date_module.today() - timedelta(days=days)).isoformat()

    # YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value

    # "M월 D일"
    m = re.fullmatch(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", value)
    if m:
        year = date_module.today().year
        month = int(m.group(1))
        day = int(m.group(2))
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
    try:
        return int(cleaned)
    except ValueError:
        return None


def is_item_substring(message: str, item: Optional[str]) -> bool:
    """
    Prevent hallucinated items: item must be present in user message.
    Uses both raw and whitespace-stripped comparisons.
    """
    if not item:
        return False
    msg = (message or "").strip()
    it = item.strip()
    if not msg or not it:
        return False

    msg_compact = re.sub(r"\s+", "", msg)
    it_compact = re.sub(r"\s+", "", it)

    return (it in msg) or (it_compact in msg_compact)


def minimal_fallback_intent(message: str) -> Intent:
    """
    Used only when LLM fails to return usable JSON.
    Keep it minimal to avoid 'regex-driven' behavior.
    """
    msg = message or ""
    msg_l = msg.lower()

    intent = "unknown"
    if "삭제" in msg or "delete" in msg_l:
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

    entry_date = None
    if "오늘" in msg or "today" in msg_l:
        entry_date = today_iso()
    elif "어제" in msg or "yesterday" in msg_l:
        entry_date = (date_module.today() - timedelta(days=1)).isoformat()

    amount = None
    m = re.search(r"([\d,]+)\s*원", msg)
    if m:
        amount = normalize_amount(m.group(1))

    return Intent(intent=intent, date=entry_date, item=None, amount=amount, target=target)


def extract_intent(message: str, llm: OllamaLLM | FakeLLM, prompt: str) -> Intent:
    """
    LLM-first extraction. If LLM fails, fallback minimally.
    Also validates item against user message to prevent hallucinations.
    """
    data = {}
    try:
        output = llm.chat(prompt, message)
        parsed = parse_intent_from_llm(output)
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}

    if not data or "intent" not in data:
        return minimal_fallback_intent(message)

    intent = str(data.get("intent", "unknown")).strip().lower()
    if intent not in {"insert", "select", "update", "delete", "unknown"}:
        intent = "unknown"
    if intent == "unknown":
        fallback = minimal_fallback_intent(message)
        if fallback.intent != "unknown":
            return fallback

    date_value = normalize_relative_date(data.get("date")) if data.get("date") else None

    item_value = data.get("item")
    item = str(item_value).strip() if item_value else None
    # ✅ hallucination guard
    if item and not is_item_substring(message, item):
        item = None

    amount = normalize_amount(data.get("amount")) if data.get("amount") is not None else None

    target = data.get("target")
    target = str(target).strip() if target else None
    if target not in {None, "last"}:
        target = None

    return Intent(intent=intent, date=date_value, item=item, amount=amount, target=target)


def format_entries(entries: list[dict]) -> str:
    if not entries:
        return "내역이 없어요."
    lines = []
    for idx, entry in enumerate(entries, start=1):
        lines.append(f"{idx}) {entry['date']} {entry['item']} {entry['amount']}원 (id:{entry['id']})")
    return "\n".join(lines)


def filter_entries_by_item(entries: list[dict], item: Optional[str]) -> list[dict]:
    if not item:
        return entries

    needle = re.sub(r"\s+", "", item).lower()
    if not needle:
        return entries

    out = []
    for entry in entries:
        hay = re.sub(r"\s+", "", str(entry.get("item", ""))).lower()
        if needle in hay:
            out.append(entry)
    return out


def build_graph(db_path: Optional[str], llm: OllamaLLM | FakeLLM, prompt: str):
    YES = {"yes", "y", "네", "응", "확인", "진행", "삭제해", "해줘"}
    NO = {"no", "n", "아니", "취소", "안해", "안 할래"}

    def handle_confirm_if_any(state: ChatState) -> Optional[ChatState]:
        pending_action = state.get("pending_action")
        pending_confirm = state.get("pending_confirm")
        if not pending_action or not pending_confirm:
            return None

        msg = (state.get("message") or "").strip().lower()
        token = pending_action.get("token")
        if not token or pending_confirm.get("token") != token:
            return None

        if msg in YES:
            action = pending_action.get("action")
            if action == "delete":
                entry_id = pending_action.get("entry_id")
                ok = delete_entry(db_path, entry_id)
                if not ok:
                    return {"reply": "삭제에 실패했어요.", "pending_confirm": None, "pending_action": None}
                return {"reply": "삭제 완료했어요.", "pending_confirm": None, "pending_action": None}
            return {"reply": "지원하지 않는 확인 작업이에요.", "pending_confirm": None, "pending_action": None}

        if msg in NO:
            return {"reply": "취소했어요.", "pending_confirm": None, "pending_action": None}

        return {
            "reply": "확인/취소 중 하나로 답해주세요. (yes/no)",
            "pending_confirm": pending_confirm,
            "pending_action": pending_action,
        }

    def handle_selection_if_any(state: ChatState) -> Optional[ChatState]:
        sel = state.get("pending_selection")
        if not sel:
            return None

        msg = (state.get("message") or "").strip()
        msg_l = msg.lower()
        candidates = sel.get("candidates", [])

        if "취소" in msg or msg_l in {"cancel", "no", "n"}:
            return {"reply": "선택을 취소했어요.", "pending_selection": None}

        m = re.search(r"(\d+)", msg)
        if not m:
            return {
                "reply": "수정/삭제할 항목의 id를 보내주세요.\n" + format_entries(candidates),
                "pending_selection": sel,
            }

        chosen_id = int(m.group(1))
        if not any(c["id"] == chosen_id for c in candidates):
            return {
                "reply": "후보 목록에 없는 id예요. 다시 골라주세요.\n" + format_entries(candidates),
                "pending_selection": sel,
            }

        action = sel.get("action")

        if action == "update":
            amount = sel.get("amount")
            if amount is None:
                return {"reply": "바꿀 금액이 없어요. 다시 말씀해 주세요.", "pending_selection": None}

            updated = update_entry_amount(db_path, chosen_id, amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", "pending_selection": None}

            return {
                "reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원",
                "pending_selection": None,
            }

        if action == "delete":
            entry = next(c for c in candidates if c["id"] == chosen_id)
            token = uuid.uuid4().hex
            return {
                "reply": f"삭제할까요? {entry['date']} {entry['item']} {entry['amount']}원",
                "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                "pending_action": {"token": token, "action": "delete", "entry_id": entry["id"]},
                "pending_selection": None,
            }

        return {"reply": "알 수 없는 선택 작업이에요.", "pending_selection": None}

    def process(state: ChatState) -> ChatState:
        # 0) pending 먼저 소비
        out = handle_confirm_if_any(state)
        if out:
            return out

        out = handle_selection_if_any(state)
        if out:
            return out

        message = state.get("message", "")
        if not message:
            return {"reply": "메시지가 비어 있어요."}

        # ✅ today 주입: 상대 날짜(어제 등) ISO 변환을 모델이 할 수 있게 함
        prompt_with_today = prompt.replace("{today}", today_iso())

        intent = extract_intent(message, llm, prompt_with_today)

        # 새 intent 처리 시, 오래된 pending 정리
        cleanup: ChatState = {"pending_confirm": None, "pending_action": None, "pending_selection": None}

        if intent.intent == "insert":
            entry_date = intent.date or today_iso()

            if intent.amount is None:
                return {"reply": "금액을 알려주세요.", **cleanup}
            if not intent.item:
                return {"reply": "항목(상품/가게명)을 알려주세요.", **cleanup}

            entry = insert_entry(db_path, entry_date, intent.item, intent.amount)
            return {"reply": f"저장했어요: {entry['date']} {entry['item']} {entry['amount']}원", **cleanup}

        if intent.intent == "select":
            entry_date = intent.date or today_iso()
            entries = list_entries(db_path, entry_date=entry_date, limit=10)
            return {"reply": format_entries(entries), **cleanup}

        if intent.intent == "update":
            if intent.amount is None:
                return {"reply": "바꿀 금액을 알려주세요.", **cleanup}

            target = intent.target
            if target == "last":
                entry = get_last_entry(db_path)
                if not entry:
                    return {"reply": "최근 내역이 없어요.", **cleanup}

                updated = update_entry_amount(db_path, entry["id"], intent.amount)
                if not updated:
                    return {"reply": "수정에 실패했어요.", **cleanup}

                return {"reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원", **cleanup}

            if intent.item or intent.date:
                candidates = list_entries(db_path, entry_date=intent.date, limit=100)
                candidates = filter_entries_by_item(candidates, intent.item)
                if not candidates:
                    return {"reply": "조건에 맞는 수정 대상이 없어요.", **cleanup}
            else:
                entry = get_last_entry(db_path)
                if not entry:
                    return {"reply": "최근 내역이 없어요.", **cleanup}
                candidates = [entry]

            if not candidates:
                return {"reply": "수정할 내역이 없어요.", **cleanup}
            if len(candidates) == 1:
                updated = update_entry_amount(db_path, candidates[0]["id"], intent.amount)
                if not updated:
                    return {"reply": "수정에 실패했어요.", **cleanup}
                return {"reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원", **cleanup}

            return {
                "reply": "어느 항목을 수정할까요? id를 알려주세요.\n" + format_entries(candidates),
                "pending_selection": {"action": "update", "amount": intent.amount, "candidates": candidates},
                "pending_confirm": None,
                "pending_action": None,
            }

        if intent.intent == "delete":
            target = intent.target

            if target == "last":
                entry = get_last_entry(db_path)
                if not entry:
                    return {"reply": "삭제할 내역이 없어요.", **cleanup}

                token = uuid.uuid4().hex
                return {
                    "reply": f"삭제할까요? {entry['date']} {entry['item']} {entry['amount']}원",
                    "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                    "pending_action": {"token": token, "action": "delete", "entry_id": entry["id"]},
                    "pending_selection": None,
                }

            if intent.item or intent.date:
                candidates = list_entries(db_path, entry_date=intent.date, limit=100)
                candidates = filter_entries_by_item(candidates, intent.item)
                if not candidates:
                    return {"reply": "조건에 맞는 삭제 대상이 없어요.", **cleanup}
            else:
                entry = get_last_entry(db_path)
                if not entry:
                    return {"reply": "삭제할 내역이 없어요.", **cleanup}
                candidates = [entry]

            if not candidates:
                return {"reply": "삭제할 내역이 없어요.", **cleanup}
            if len(candidates) == 1:
                entry = candidates[0]
                token = uuid.uuid4().hex
                return {
                    "reply": f"삭제할까요? {entry['date']} {entry['item']} {entry['amount']}원",
                    "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                    "pending_action": {"token": token, "action": "delete", "entry_id": entry["id"]},
                    "pending_selection": None,
                }

            return {
                "reply": "어느 항목을 삭제할까요? id를 알려주세요.\n" + format_entries(candidates),
                "pending_selection": {"action": "delete", "candidates": candidates},
                "pending_confirm": None,
                "pending_action": None,
            }

        return {"reply": "무슨 뜻인지 잘 모르겠어요.", **cleanup}

    builder = StateGraph(ChatState)
    builder.add_node("process", process)
    builder.set_entry_point("process")
    builder.add_edge("process", END)
    return builder.compile()
