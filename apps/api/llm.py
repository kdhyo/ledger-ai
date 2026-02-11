from __future__ import annotations

import json
import os
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
        return json.dumps({"intent": "unknown", "date": None, "item": None, "amount": None, "target": None})


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
