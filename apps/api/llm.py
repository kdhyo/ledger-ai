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
        "intent": {"type": "string", "enum": ["insert", "select", "update", "delete", "unknown"]},
        "date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "item": {"type": ["string", "null"]},
        "amount": {"type": ["integer", "null"]},
        "target": {"type": ["string", "null"], "enum": ["last", None]},
    },
    "required": ["intent", "date", "item", "amount", "target"],
}


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


class FakeLLM:
    def chat(self, system_prompt: str, user_message: str) -> str:
        msg = (user_message or "").strip()
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
            entry_date = date_module.today().isoformat()
        elif "어제" in msg or "yesterday" in msg_l:
            entry_date = (date_module.today() - timedelta(days=1)).isoformat()
        elif "그제" in msg or "엊그제" in msg or "2 days ago" in msg_l:
            entry_date = (date_module.today() - timedelta(days=2)).isoformat()

        amount = None
        amount_matches = re.findall(r"([\d,]+)\s*원", msg)
        if amount_matches:
            amount = int(re.sub(r"[^0-9]", "", amount_matches[-1]))
        else:
            num_matches = re.findall(r"\b\d[\d,]*\b", msg)
            if num_matches:
                amount = int(re.sub(r"[^0-9]", "", num_matches[-1]))

        item = None
        if intent == "insert":
            patterns = [
                r"(?:오늘|어제|그제|엊그제)\s+(.+?)\s*([\d,]+)\s*원",
                r"(?:today|yesterday)\s+(.+?)\s*(\d[\d,]*)\s*(?:won)?",
                r"^\s*(.+?)\s*([\d,]+)\s*원",
            ]
            for pat in patterns:
                m = re.search(pat, msg, flags=re.I)
                if m:
                    candidate = m.group(1).strip()
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


def get_llm(use_fake: bool = False) -> OllamaLLM | FakeLLM:
    if use_fake or os.getenv("USE_FAKE_LLM") == "1":
        return FakeLLM()

    model = os.getenv("OLLAMA_MODEL", "bnksys/yanolja-eeve-korean-instruct-10.8b")
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
