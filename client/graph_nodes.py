from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from .graph_helpers import cleanup_state, filter_entries_by_item, format_entries
from .graph_intent import extract_bulk_insert_candidates, extract_date_from_message, extract_intent
from .graph_prompts import render_read_tool_system_prompt, render_read_tool_user_prompt
from .graph_state import ChatState
from .llm import FakeLLM, OllamaLLM
from .mcp import build_mcp_client
from shared.time_utils import today_iso

logger = logging.getLogger(__name__)


class LedgerGraphNodes:
    def __init__(self, db_path: Optional[str], llm: OllamaLLM | FakeLLM, prompt: str) -> None:
        self.db_path = db_path
        self.llm = llm
        self.prompt = prompt
        self.mcp_client = build_mcp_client(db_path=db_path)
        self.yes = {"yes", "y", "네", "응", "확인", "진행", "삭제해", "해줘"}
        self.no = {"no", "n", "아니", "취소", "안해", "안 할래"}

    def _prompt_with_today(self) -> str:
        return self.prompt.replace("{today}", today_iso())

    def _invoke_tool(self, tool_name: str, payload: dict, *, default):
        try:
            return self.mcp_client.invoke(tool_name, payload)
        except Exception:
            logger.exception("Tool invocation failed: %s", tool_name)
            return default

    def _try_read_via_mcp_tool_call(self, state: ChatState):
        if isinstance(self.llm, FakeLLM):
            return None
        if not hasattr(self.llm, "chat_with_tools"):
            return None

        intent = state.get("intent", "select")
        entry_date = state.get("intent_date") or today_iso()
        message = state.get("message", "")
        resource_context = self.mcp_client.get_read_resource_context(entry_date=entry_date, limit=5)
        system_prompt = render_read_tool_system_prompt(resource_context)
        user_prompt = render_read_tool_user_prompt(message, str(intent), entry_date)

        try:
            llm_message = self.llm.chat_with_tools(system_prompt, user_prompt, self.mcp_client.get_read_tool_schemas())
        except Exception:
            logger.warning("LLM read tool-call generation failed; fallback path used", exc_info=True)
            return None

        tool_calls = llm_message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            return None

        function_payload = tool_calls[0].get("function") if isinstance(tool_calls[0], dict) else None
        if not isinstance(function_payload, dict):
            return None

        name = function_payload.get("name")
        arguments = function_payload.get("arguments")
        if not isinstance(name, str):
            return None

        if name == "list_ledger_entries" and isinstance(arguments, dict):
            arguments.setdefault("entry_date", entry_date)
            arguments.setdefault("limit", 10)
        if name == "sum_ledger_entries" and isinstance(arguments, dict):
            arguments.setdefault("entry_date", entry_date)

        try:
            result = self.mcp_client.invoke(name, arguments)
        except Exception:
            logger.exception("MCP read tool execution failed: %s", name)
            return None

        if name == "list_ledger_entries":
            return {"reply": format_entries(result), **cleanup_state()}
        if name == "sum_ledger_entries":
            query_date = None
            if isinstance(arguments, dict):
                query_date = arguments.get("entry_date")
            query_date = query_date or entry_date
            return {"reply": f"{query_date} 총합은 {result}원이에요.", **cleanup_state()}
        if name == "get_last_ledger_entry":
            if not result:
                return {"reply": "최근 내역이 없어요.", **cleanup_state()}
            return {
                "reply": f"최근 내역: {result['date']} {result['item']} {result['amount']}원",
                **cleanup_state(),
            }
        return None

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
                ok = self._invoke_tool(
                    "delete_ledger_entry",
                    {"db_path": self.db_path, "entry_id": pending_action.get("entry_id")},
                    default=False,
                )
                if ok:
                    return {"reply": "삭제 완료했어요.", **cleanup_state()}
                return {"reply": "삭제 처리 중 오류가 발생했어요.", **cleanup_state()}
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
            updated = self._invoke_tool(
                "update_ledger_entry_amount",
                {"db_path": self.db_path, "entry_id": chosen_id, "new_amount": amount},
                default=None,
            )
            if not updated:
                return {"reply": "수정 처리 중 오류가 발생했어요.", **cleanup_state()}
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
        resource_context = self.mcp_client.get_read_resource_context(
            entry_date=extract_date_from_message(message),
            limit=3,
        )
        prompt_with_resources = f"{self._prompt_with_today()}\n\nContext resources:\n{resource_context}"
        parsed = extract_intent(message, self.llm, prompt_with_resources)
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
            saved = []
            for candidate in candidates:
                entry = self._invoke_tool(
                    "insert_ledger_entry",
                    {
                        "db_path": self.db_path,
                        "entry_date": candidate["date"],
                        "item": candidate["item"],
                        "amount": candidate["amount"],
                    },
                    default=None,
                )
                if not entry:
                    return {"reply": "저장 처리 중 오류가 발생했어요.", **cleanup_state()}
                saved.append(entry)
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

        entry = self._invoke_tool(
            "insert_ledger_entry",
            {"db_path": self.db_path, "entry_date": entry_date, "item": item, "amount": amount},
            default=None,
        )
        if not entry:
            return {"reply": "저장 처리 중 오류가 발생했어요.", **cleanup_state()}
        return {"reply": f"저장했어요: {entry['date']} {entry['item']} {entry['amount']}원", **cleanup_state()}

    def run_select_node(self, state: ChatState) -> ChatState:
        direct = self._try_read_via_mcp_tool_call(state)
        if direct:
            return direct

        entry_date = state.get("intent_date") or today_iso()
        entries = self._invoke_tool(
            "list_ledger_entries",
            {"db_path": self.db_path, "entry_date": entry_date, "limit": 10},
            default=None,
        )
        if entries is None:
            return {"reply": "내역 조회 중 오류가 발생했어요.", **cleanup_state()}
        return {"reply": format_entries(entries), **cleanup_state()}

    def run_sum_node(self, state: ChatState) -> ChatState:
        direct = self._try_read_via_mcp_tool_call(state)
        if direct:
            return direct

        entry_date = state.get("intent_date") or today_iso()
        total = self._invoke_tool(
            "sum_ledger_entries",
            {"db_path": self.db_path, "entry_date": entry_date},
            default=None,
        )
        if total is None:
            return {"reply": "합계 계산 중 오류가 발생했어요.", **cleanup_state()}
        return {"reply": f"{entry_date} 총합은 {total}원이에요.", **cleanup_state()}

    def run_update_prepare_node(self, state: ChatState) -> ChatState:
        amount = state.get("intent_amount")
        target = state.get("intent_target")
        item = state.get("intent_item")
        entry_date = state.get("intent_date")

        if amount is None:
            return {"reply": "바꿀 금액을 알려주세요.", **cleanup_state()}

        if target == "last":
            entry = self._invoke_tool("get_last_ledger_entry", {"db_path": self.db_path}, default=None)
            if not entry:
                return {"reply": "최근 내역이 없어요.", **cleanup_state()}
            updated = self._invoke_tool(
                "update_ledger_entry_amount",
                {"db_path": self.db_path, "entry_id": entry["id"], "new_amount": amount},
                default=None,
            )
            if not updated:
                return {"reply": "수정 처리 중 오류가 발생했어요.", **cleanup_state()}
            return {
                "reply": f"수정했어요: {updated['date']} {updated['item']} {updated['amount']}원",
                **cleanup_state(),
            }

        if item or entry_date:
            candidates = self._invoke_tool(
                "list_ledger_entries",
                {"db_path": self.db_path, "entry_date": entry_date, "limit": 100},
                default=None,
            )
            if candidates is None:
                return {"reply": "내역 조회 중 오류가 발생했어요.", **cleanup_state()}
            candidates = filter_entries_by_item(candidates, item)
            if not candidates:
                return {"reply": "조건에 맞는 수정 대상이 없어요.", **cleanup_state()}
        else:
            last = self._invoke_tool("get_last_ledger_entry", {"db_path": self.db_path}, default=None)
            if not last:
                return {"reply": "최근 내역이 없어요.", **cleanup_state()}
            candidates = [last]

        if len(candidates) == 1:
            updated = self._invoke_tool(
                "update_ledger_entry_amount",
                {"db_path": self.db_path, "entry_id": candidates[0]["id"], "new_amount": amount},
                default=None,
            )
            if not updated:
                return {"reply": "수정 처리 중 오류가 발생했어요.", **cleanup_state()}
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
            entry = self._invoke_tool("get_last_ledger_entry", {"db_path": self.db_path}, default=None)
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
            candidates = self._invoke_tool(
                "list_ledger_entries",
                {"db_path": self.db_path, "entry_date": entry_date, "limit": 100},
                default=None,
            )
            if candidates is None:
                return {"reply": "내역 조회 중 오류가 발생했어요.", **cleanup_state()}
            candidates = filter_entries_by_item(candidates, item)
            if not candidates:
                return {"reply": "조건에 맞는 삭제 대상이 없어요.", **cleanup_state()}
        else:
            last = self._invoke_tool("get_last_ledger_entry", {"db_path": self.db_path}, default=None)
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
