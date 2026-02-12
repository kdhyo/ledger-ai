from __future__ import annotations

import json
import os
import re
from datetime import date as date_module, timedelta
from typing import Any, Optional

import requests


LEDGER_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string", "enum": ["insert", "select", "update", "delete", "sum", "unknown"]},
        "date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "item": {"type": ["string", "null"]},
        "amount": {"type": ["integer", "null"]},
        "target": {"type": ["string", "null"], "enum": ["last", None]},
    },
    "required": ["intent", "date", "item", "amount", "target"],
}


def normalize_amount_text(value: str) -> Optional[int]:
    text = (value or "").strip().lower()
    if not text:
        return None
    text = text.replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(천|만)?\s*(원)?", text)
    if match:
        number = float(match.group(1))
        unit = match.group(2)
        scale = 1
        if unit == "천":
            scale = 1000
        elif unit == "만":
            scale = 10000
        return int(number * scale)
    cleaned = re.sub(r"[^0-9]", "", text)
    if not cleaned:
        return None
    return int(cleaned)


class OllamaLLM:
    def __init__(
        self,
        model: str,
        base_url: str,
        temperature: float = 0.0,
        top_p: float = 0.2,
        seed: Optional[int] = 42,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed

    def chat(self, system_prompt: str, user_message: str) -> str:
        """
        Uses Ollama /api/chat with structured outputs:
        - format: JSON schema to strongly constrain output
        - low randomness options to reduce hallucinated fields/values
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            # Structured output (Ollama)
            "format": LEDGER_INTENT_SCHEMA,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        if self.seed is not None:
            payload["options"]["seed"] = self.seed

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

    def chat_with_tools(self, system_prompt: str, user_message: str, tools: list[dict]) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "tools": tools,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
        }
        if self.seed is not None:
            payload["options"]["seed"] = self.seed

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=30,
        )
        if not response.ok:
            body_preview = (response.text or "")[:500]
            raise RuntimeError(
                f"Ollama tool call failed: HTTP {response.status_code}, body={body_preview}"
            )
        data = response.json()
        message = data.get("message")
        return message if isinstance(message, dict) else {}


class FakeLLM:
    def chat(self, system_prompt: str, user_message: str) -> str:
        msg = (user_message or "").strip()
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
        elif re.search(r"([\d,]+(?:\s*[천만])?)\s*원", msg) or re.search(r"\b\d+\b", msg_l):
            intent = "insert"

        target = None
        if any(k in msg for k in ["방금", "최근", "그거", "그것", "마지막"]) or "last" in msg_l:
            target = "last"

        entry_date = None
        if "오늘" in msg or "today" in msg_l:
            entry_date = date_module.today().isoformat()
        elif "어제" in msg or "yesterday" in msg_l:
            entry_date = (date_module.today() - timedelta(days=1)).isoformat()
        elif "그제" in msg or "엊그제" in msg or "2 days ago" in msg_l:
            entry_date = (date_module.today() - timedelta(days=2)).isoformat()
        else:
            m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", msg)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    entry_date = date_module(y, mo, d).isoformat()
                except ValueError:
                    entry_date = None
            if entry_date is None:
                m = re.search(r"\b(\d{2,4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\b", msg)
                if m:
                    y_raw, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    y = 2000 + y_raw if y_raw < 100 else y_raw
                    try:
                        entry_date = date_module(y, mo, d).isoformat()
                    except ValueError:
                        entry_date = None
            if entry_date is None:
                m = re.search(r"\b(\d{1,2})\s*일\b(?!\s*전)", msg)
                if m:
                    today = date_module.today()
                    d = int(m.group(1))
                    try:
                        entry_date = date_module(today.year, today.month, d).isoformat()
                    except ValueError:
                        entry_date = None

        amount = None
        amount_matches = re.findall(r"([\d,]+(?:\s*[천만])?)\s*원", msg)
        if amount_matches:
            amount = normalize_amount_text(amount_matches[-1])
        else:
            num_matches = re.findall(r"\b\d[\d,]*\b", msg)
            if num_matches:
                amount = normalize_amount_text(num_matches[-1])

        item = None
        if intent == "insert":
            patterns = [
                r"(?:\d{4}-\d{1,2}-\d{1,2})\s+(.+?)\s*([\d,]+(?:\s*[천만])?)\s*원",
                r"(?:오늘|어제|그제|엊그제)\s+(.+?)\s*([\d,]+(?:\s*[천만])?)\s*원",
                r"(?:today|yesterday)\s+(.+?)\s*(\d[\d,]*)\s*(?:won)?",
                r"^\s*(.+?)\s*([\d,]+(?:\s*[천만])?)\s*원",
            ]
            for pat in patterns:
                m = re.search(pat, msg, flags=re.I)
                if m:
                    candidate = m.group(1).strip()
                    if candidate:
                        item = candidate
                        break
        elif intent in {"update", "delete"}:
            patterns = [
                r"[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]\s*(?:아이템)?\s*(?:을|를)?\s*(?:삭제|지워|수정|바꿔|update|delete|change)",
                r"([가-힣A-Za-z0-9_][가-힣A-Za-z0-9_\s]{0,30})\s*아이템\s*(?:을|를)?\s*(?:삭제|지워|수정|바꿔)",
                r"(?:삭제|지워|수정|바꿔)\s*해?\s*줘?\s*([가-힣A-Za-z0-9_][가-힣A-Za-z0-9_\s]{0,30})",
            ]
            for pat in patterns:
                m = re.search(pat, msg, flags=re.I)
                if m:
                    candidate = m.group(1).strip()
                    candidate = re.sub(r"^(?:에|의)\s*", "", candidate)
                    if candidate:
                        item = candidate
                        break

        return json.dumps(
            {
                "intent": intent,
                "date": entry_date,
                "item": item,
                "amount": amount,
                "target": target,
            }
        )

    def chat_with_tools(self, system_prompt: str, user_message: str, tools: list[dict]) -> dict:
        msg = (user_message or "").lower()
        if any(k in msg for k in ["sum", "total", "총합", "합계"]):
            return {
                "tool_calls": [
                    {"function": {"name": "sum_ledger_entries", "arguments": {}}},
                ]
            }
        if any(k in msg for k in ["last", "최근", "마지막"]):
            return {
                "tool_calls": [
                    {"function": {"name": "get_last_ledger_entry", "arguments": {}}},
                ]
            }
        return {
            "tool_calls": [
                {"function": {"name": "list_ledger_entries", "arguments": {"limit": 10}}},
            ]
        }


def get_llm(use_fake: bool = False) -> OllamaLLM | FakeLLM:
    if use_fake or os.getenv("USE_FAKE_LLM") == "1":
        return FakeLLM()

    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))
    top_p = float(os.getenv("OLLAMA_TOP_P", "0.2"))
    seed_env = os.getenv("OLLAMA_SEED", "42")
    seed = None if seed_env.lower() in {"none", "null", ""} else int(seed_env)

    return OllamaLLM(
        model=model,
        base_url=base_url,
        temperature=temperature,
        top_p=top_p,
        seed=seed,
    )
