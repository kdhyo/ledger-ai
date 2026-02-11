from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date as date_module, timedelta
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from .llm import FakeLLM, OllamaLLM
from .tools.ledger_tools import (
    delete_entry,
    get_last_entry,
    insert_entry,
    list_entries,
    sum_entries,
    today_iso,
    update_entry_amount,
)


class ChatState(TypedDict, total=False):
    message: str
    reply: str
    pending_confirm: Optional[dict]
    pending_action: Optional[dict]
    pending_selection: Optional[dict]
    intent: str
    intent_date: Optional[str]
    intent_item: Optional[str]
    intent_amount: Optional[int]
    intent_target: Optional[str]


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
    try:
        return int(cleaned)
    except ValueError:
        return None


def is_item_substring(message: str, item: Optional[str]) -> bool:
    if not item:
        return False
    msg = (message or "").strip()
    it = item.strip()
    if not msg or not it:
        return False
    return it in msg or re.sub(r"\s+", "", it) in re.sub(r"\s+", "", msg)


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

    entry_date = None
    date_patterns = [
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{2,4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일",
        r"\d{1,2}\s*월\s*\d{1,2}\s*일",
        r"\d+\s*일\s*전",
        r"\d+\s*days?\s*ago",
    ]
    for pat in date_patterns:
        m_date = re.search(pat, msg, re.I)
        if m_date:
            entry_date = normalize_relative_date(m_date.group(0))
            break
    if entry_date is None:
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

    def cleanup() -> ChatState:
        return {"pending_confirm": None, "pending_action": None, "pending_selection": None}

    def entry_node(state: ChatState) -> ChatState:
        return state

    def route_from_entry(state: ChatState) -> str:
        if not (state.get("message") or "").strip():
            return "empty"
        if state.get("pending_confirm") and state.get("pending_action"):
            return "confirm"
        if state.get("pending_selection"):
            return "selection"
        return "extract"

    def empty_message_node(state: ChatState) -> ChatState:
        return {"reply": "메시지가 비어 있어요."}

    def confirm_decision_node(state: ChatState) -> ChatState:
        pending_action = state.get("pending_action")
        pending_confirm = state.get("pending_confirm")
        if not pending_action or not pending_confirm:
            return {"reply": "확인할 항목이 없어요.", **cleanup()}

        msg = (state.get("message") or "").strip().lower()
        if msg in YES:
            if pending_action.get("action") == "delete":
                ok = delete_entry(db_path, pending_action.get("entry_id"))
                if ok:
                    return {"reply": "삭제 완료했어요.", **cleanup()}
                return {"reply": "삭제에 실패했어요.", **cleanup()}
            return {"reply": "지원하지 않는 확인 작업이에요.", **cleanup()}

        if msg in NO:
            return {"reply": "취소했어요.", **cleanup()}

        return {
            "reply": "확인/취소 중 하나로 답해주세요. (yes/no)",
            "pending_confirm": pending_confirm,
            "pending_action": pending_action,
            "pending_selection": state.get("pending_selection"),
        }

    def selection_decision_node(state: ChatState) -> ChatState:
        sel = state.get("pending_selection")
        if not sel:
            return {"reply": "선택할 항목이 없어요.", **cleanup()}

        msg = (state.get("message") or "").strip()
        msg_l = msg.lower()
        candidates = sel.get("candidates", [])

        if "취소" in msg or msg_l in {"cancel", "no", "n"}:
            return {"reply": "선택을 취소했어요.", **cleanup()}

        m = re.search(r"(\d+)", msg)
        if not m:
            return {
                "reply": "수정/삭제할 항목의 id를 보내주세요.\n" + format_entries(candidates),
                "pending_selection": sel,
                "pending_confirm": state.get("pending_confirm"),
                "pending_action": state.get("pending_action"),
            }

        chosen_id = int(m.group(1))
        chosen = next((c for c in candidates if c["id"] == chosen_id), None)
        if not chosen:
            return {
                "reply": "후보 목록에 없는 id예요. 다시 골라주세요.\n" + format_entries(candidates),
                "pending_selection": sel,
                "pending_confirm": state.get("pending_confirm"),
                "pending_action": state.get("pending_action"),
            }

        action = sel.get("action")
        if action == "update":
            amount = sel.get("amount")
            if amount is None:
                return {"reply": "바꿀 금액이 없어요. 다시 말씀해 주세요.", **cleanup()}
            updated = update_entry_amount(db_path, chosen_id, amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", **cleanup()}
            return {"reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원", **cleanup()}

        if action == "delete":
            token = uuid.uuid4().hex
            return {
                "reply": f"삭제할까요? {chosen['date']} {chosen['item']} {chosen['amount']}원",
                "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                "pending_action": {"token": token, "action": "delete", "entry_id": chosen_id},
                "pending_selection": None,
            }

        return {"reply": "알 수 없는 선택 작업이에요.", **cleanup()}

    def extract_intent_node(state: ChatState) -> ChatState:
        message = state.get("message", "")
        prompt_with_today = prompt.replace("{today}", today_iso())
        parsed = extract_intent(message, llm, prompt_with_today)
        return {
            "intent": parsed.intent,
            "intent_date": parsed.date,
            "intent_item": parsed.item,
            "intent_amount": parsed.amount,
            "intent_target": parsed.target,
        }

    def route_intent(state: ChatState) -> str:
        intent = state.get("intent", "unknown")
        if intent == "insert":
            return "insert"
        if intent == "select":
            return "select"
        if intent == "sum":
            return "sum"
        if intent == "update":
            return "update"
        if intent == "delete":
            return "delete"
        return "unknown"

    def run_insert_node(state: ChatState) -> ChatState:
        amount = state.get("intent_amount")
        item = state.get("intent_item")
        entry_date = state.get("intent_date") or today_iso()
        if amount is None:
            return {"reply": "금액을 알려주세요.", **cleanup()}
        if not item:
            return {"reply": "항목(상품/가게명)을 알려주세요.", **cleanup()}
        entry = insert_entry(db_path, entry_date, item, amount)
        return {"reply": f"저장했어요: {entry['date']} {entry['item']} {entry['amount']}원", **cleanup()}

    def run_select_node(state: ChatState) -> ChatState:
        entry_date = state.get("intent_date") or today_iso()
        entries = list_entries(db_path, entry_date=entry_date, limit=10)
        return {"reply": format_entries(entries), **cleanup()}

    def run_sum_node(state: ChatState) -> ChatState:
        entry_date = state.get("intent_date") or today_iso()
        total = sum_entries(db_path, entry_date=entry_date)
        return {"reply": f"{entry_date} 총합은 {total}원이에요.", **cleanup()}

    def run_update_prepare_node(state: ChatState) -> ChatState:
        amount = state.get("intent_amount")
        target = state.get("intent_target")
        item = state.get("intent_item")
        entry_date = state.get("intent_date")

        if amount is None:
            return {"reply": "바꿀 금액을 알려주세요.", **cleanup()}

        if target == "last":
            entry = get_last_entry(db_path)
            if not entry:
                return {"reply": "최근 내역이 없어요.", **cleanup()}
            updated = update_entry_amount(db_path, entry["id"], amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", **cleanup()}
            return {"reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원", **cleanup()}

        if item or entry_date:
            candidates = list_entries(db_path, entry_date=entry_date, limit=100)
            candidates = filter_entries_by_item(candidates, item)
            if not candidates:
                return {"reply": "조건에 맞는 수정 대상이 없어요.", **cleanup()}
        else:
            last = get_last_entry(db_path)
            if not last:
                return {"reply": "최근 내역이 없어요.", **cleanup()}
            candidates = [last]

        if len(candidates) == 1:
            updated = update_entry_amount(db_path, candidates[0]["id"], amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", **cleanup()}
            return {"reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원", **cleanup()}

        return {
            "reply": "어느 항목을 수정할까요? id를 알려주세요.\n" + format_entries(candidates),
            "pending_selection": {"action": "update", "amount": amount, "candidates": candidates},
            "pending_confirm": None,
            "pending_action": None,
        }

    def run_delete_prepare_node(state: ChatState) -> ChatState:
        target = state.get("intent_target")
        item = state.get("intent_item")
        entry_date = state.get("intent_date")

        if target == "last":
            entry = get_last_entry(db_path)
            if not entry:
                return {"reply": "삭제할 내역이 없어요.", **cleanup()}
            token = uuid.uuid4().hex
            return {
                "reply": f"삭제할까요? {entry['date']} {entry['item']} {entry['amount']}원",
                "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                "pending_action": {"token": token, "action": "delete", "entry_id": entry["id"]},
                "pending_selection": None,
            }

        if item or entry_date:
            candidates = list_entries(db_path, entry_date=entry_date, limit=100)
            candidates = filter_entries_by_item(candidates, item)
            if not candidates:
                return {"reply": "조건에 맞는 삭제 대상이 없어요.", **cleanup()}
        else:
            last = get_last_entry(db_path)
            if not last:
                return {"reply": "삭제할 내역이 없어요.", **cleanup()}
            candidates = [last]

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

    def run_unknown_node(state: ChatState) -> ChatState:
        return {"reply": "무슨 뜻인지 잘 모르겠어요.", **cleanup()}

    builder = StateGraph(ChatState)
    builder.add_node("entry", entry_node)
    builder.add_node("empty_message", empty_message_node)
    builder.add_node("confirm_decision", confirm_decision_node)
    builder.add_node("selection_decision", selection_decision_node)
    builder.add_node("extract_intent", extract_intent_node)
    builder.add_node("run_insert", run_insert_node)
    builder.add_node("run_select", run_select_node)
    builder.add_node("run_sum", run_sum_node)
    builder.add_node("run_update_prepare", run_update_prepare_node)
    builder.add_node("run_delete_prepare", run_delete_prepare_node)
    builder.add_node("run_unknown", run_unknown_node)

    builder.set_entry_point("entry")
    builder.add_conditional_edges(
        "entry",
        route_from_entry,
        {
            "empty": "empty_message",
            "confirm": "confirm_decision",
            "selection": "selection_decision",
            "extract": "extract_intent",
        },
    )
    builder.add_conditional_edges(
        "extract_intent",
        route_intent,
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
