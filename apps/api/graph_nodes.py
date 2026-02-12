from __future__ import annotations

import re
import uuid
from typing import Optional

from .graph_helpers import cleanup_state, filter_entries_by_item, format_entries
from .graph_intent import extract_bulk_insert_candidates, extract_date_from_message, extract_intent
from .graph_state import ChatState
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


class LedgerGraphNodes:
    def __init__(self, db_path: Optional[str], llm: OllamaLLM | FakeLLM, prompt: str) -> None:
        self.db_path = db_path
        self.llm = llm
        self.prompt = prompt
        self.yes = {"yes", "y", "네", "응", "확인", "진행", "삭제해", "해줘"}
        self.no = {"no", "n", "아니", "취소", "안해", "안 할래"}

    def _prompt_with_today(self) -> str:
        return self.prompt.replace("{today}", today_iso())

    def entry_node(self, state: ChatState) -> ChatState:
        return state

    def route_from_entry(self, state: ChatState) -> str:
        if not (state.get("message") or "").strip():
            return "empty"
        if state.get("pending_confirm") and state.get("pending_action"):
            return "confirm"
        if state.get("pending_selection"):
            return "selection"
        return "extract"

    def empty_message_node(self, state: ChatState) -> ChatState:
        return {"reply": "메시지가 비어 있어요."}

    def confirm_decision_node(self, state: ChatState) -> ChatState:
        pending_action = state.get("pending_action")
        pending_confirm = state.get("pending_confirm")
        if not pending_action or not pending_confirm:
            return {"reply": "확인할 항목이 없어요.", **cleanup_state()}

        msg = (state.get("message") or "").strip().lower()
        if msg in self.yes:
            if pending_action.get("action") == "delete":
                ok = delete_entry(self.db_path, pending_action.get("entry_id"))
                if ok:
                    return {"reply": "삭제 완료했어요.", **cleanup_state()}
                return {"reply": "삭제에 실패했어요.", **cleanup_state()}
            return {"reply": "지원하지 않는 확인 작업이에요.", **cleanup_state()}

        if msg in self.no:
            return {"reply": "취소했어요.", **cleanup_state()}

        return {
            "reply": "확인/취소 중 하나로 답해주세요. (yes/no)",
            "pending_confirm": pending_confirm,
            "pending_action": pending_action,
            "pending_selection": state.get("pending_selection"),
        }

    def selection_decision_node(self, state: ChatState) -> ChatState:
        sel = state.get("pending_selection")
        if not sel:
            return {"reply": "선택할 항목이 없어요.", **cleanup_state()}

        msg = (state.get("message") or "").strip()
        msg_l = msg.lower()
        candidates = sel.get("candidates", [])

        if "취소" in msg or msg_l in {"cancel", "no", "n"}:
            return {"reply": "선택을 취소했어요.", **cleanup_state()}

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
                return {"reply": "바꿀 금액이 없어요. 다시 말씀해 주세요.", **cleanup_state()}
            updated = update_entry_amount(self.db_path, chosen_id, amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", **cleanup_state()}
            return {
                "reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원",
                **cleanup_state(),
            }

        if action == "delete":
            token = uuid.uuid4().hex
            return {
                "reply": f"삭제할까요? {chosen['date']} {chosen['item']} {chosen['amount']}원",
                "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                "pending_action": {"token": token, "action": "delete", "entry_id": chosen_id},
                "pending_selection": None,
            }

        return {"reply": "알 수 없는 선택 작업이에요.", **cleanup_state()}

    def extract_intent_node(self, state: ChatState) -> ChatState:
        message = state.get("message", "")
        parsed = extract_intent(message, self.llm, self._prompt_with_today())
        return {
            "intent": parsed.intent,
            "intent_date": parsed.date,
            "intent_item": parsed.item,
            "intent_amount": parsed.amount,
            "intent_target": parsed.target,
        }

    def route_intent(self, state: ChatState) -> str:
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

    def run_insert_node(self, state: ChatState) -> ChatState:
        message = state.get("message", "")
        amount = state.get("intent_amount")
        item = state.get("intent_item")
        entry_date = state.get("intent_date") or extract_date_from_message(message) or today_iso()

        candidates = extract_bulk_insert_candidates(
            message,
            entry_date,
            self.llm,
            self._prompt_with_today(),
        )

        if len(candidates) >= 2:
            saved = [insert_entry(self.db_path, c["date"], c["item"], c["amount"]) for c in candidates]
            lines = [f"{entry['date']} {entry['item']} {entry['amount']}원" for entry in saved]
            return {"reply": f"{len(saved)}건 저장했어요.\n" + "\n".join(lines), **cleanup_state()}

        if len(candidates) == 1 and (amount is None or not item):
            amount = candidates[0]["amount"]
            item = candidates[0]["item"]
            entry_date = candidates[0]["date"]

        if amount is None:
            return {"reply": "금액을 알려주세요.", **cleanup_state()}
        if not item:
            return {"reply": "항목(상품/가게명)을 알려주세요.", **cleanup_state()}

        entry = insert_entry(self.db_path, entry_date, item, amount)
        return {"reply": f"저장했어요: {entry['date']} {entry['item']} {entry['amount']}원", **cleanup_state()}

    def run_select_node(self, state: ChatState) -> ChatState:
        entry_date = state.get("intent_date") or today_iso()
        entries = list_entries(self.db_path, entry_date=entry_date, limit=10)
        return {"reply": format_entries(entries), **cleanup_state()}

    def run_sum_node(self, state: ChatState) -> ChatState:
        entry_date = state.get("intent_date") or today_iso()
        total = sum_entries(self.db_path, entry_date=entry_date)
        return {"reply": f"{entry_date} 총합은 {total}원이에요.", **cleanup_state()}

    def run_update_prepare_node(self, state: ChatState) -> ChatState:
        amount = state.get("intent_amount")
        target = state.get("intent_target")
        item = state.get("intent_item")
        entry_date = state.get("intent_date")

        if amount is None:
            return {"reply": "바꿀 금액을 알려주세요.", **cleanup_state()}

        if target == "last":
            entry = get_last_entry(self.db_path)
            if not entry:
                return {"reply": "최근 내역이 없어요.", **cleanup_state()}
            updated = update_entry_amount(self.db_path, entry["id"], amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", **cleanup_state()}
            return {
                "reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원",
                **cleanup_state(),
            }

        if item or entry_date:
            candidates = list_entries(self.db_path, entry_date=entry_date, limit=100)
            candidates = filter_entries_by_item(candidates, item)
            if not candidates:
                return {"reply": "조건에 맞는 수정 대상이 없어요.", **cleanup_state()}
        else:
            last = get_last_entry(self.db_path)
            if not last:
                return {"reply": "최근 내역이 없어요.", **cleanup_state()}
            candidates = [last]

        if len(candidates) == 1:
            updated = update_entry_amount(self.db_path, candidates[0]["id"], amount)
            if not updated:
                return {"reply": "수정에 실패했어요.", **cleanup_state()}
            return {
                "reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원",
                **cleanup_state(),
            }

        return {
            "reply": "어느 항목을 수정할까요? id를 알려주세요.\n" + format_entries(candidates),
            "pending_selection": {"action": "update", "amount": amount, "candidates": candidates},
            "pending_confirm": None,
            "pending_action": None,
        }

    def run_delete_prepare_node(self, state: ChatState) -> ChatState:
        target = state.get("intent_target")
        item = state.get("intent_item")
        entry_date = state.get("intent_date")

        if target == "last":
            entry = get_last_entry(self.db_path)
            if not entry:
                return {"reply": "삭제할 내역이 없어요.", **cleanup_state()}
            token = uuid.uuid4().hex
            return {
                "reply": f"삭제할까요? {entry['date']} {entry['item']} {entry['amount']}원",
                "pending_confirm": {"token": token, "prompt": "삭제 확인"},
                "pending_action": {"token": token, "action": "delete", "entry_id": entry["id"]},
                "pending_selection": None,
            }

        if item or entry_date:
            candidates = list_entries(self.db_path, entry_date=entry_date, limit=100)
            candidates = filter_entries_by_item(candidates, item)
            if not candidates:
                return {"reply": "조건에 맞는 삭제 대상이 없어요.", **cleanup_state()}
        else:
            last = get_last_entry(self.db_path)
            if not last:
                return {"reply": "삭제할 내역이 없어요.", **cleanup_state()}
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

    def run_unknown_node(self, state: ChatState) -> ChatState:
        return {"reply": "무슨 뜻인지 잘 모르겠어요.", **cleanup_state()}
