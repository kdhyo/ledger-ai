from __future__ import annotations

from langchain_core.prompts import PromptTemplate

INTENT_CHAIN_PROMPT = PromptTemplate.from_template(
    "{base_prompt}\n\nContext resources:\n{resource_context}\n\nFormatting instructions:\n{format_instructions}"
)

READ_TOOL_SYSTEM_PROMPT = PromptTemplate.from_template(
    "You are a read-only ledger assistant. "
    "Use exactly one available read tool for each query. "
    "Never call write/update/delete tools.\n\n"
    "Context resources:\n{resource_context}"
)

READ_TOOL_USER_PROMPT = PromptTemplate.from_template(
    "user_message={message}\n"
    "intent={intent}\n"
    "default_entry_date={entry_date}\n"
    "For select, prefer list_ledger_entries. For sum, prefer sum_ledger_entries."
)


def render_intent_chain_prompt(base_prompt: str, format_instructions: str, resource_context: str = "") -> str:
    context = resource_context.strip() or "(none)"
    return INTENT_CHAIN_PROMPT.format(
        base_prompt=base_prompt,
        resource_context=context,
        format_instructions=format_instructions,
    )


def render_read_tool_system_prompt(resource_context: str) -> str:
    context = resource_context.strip() or "(none)"
    return READ_TOOL_SYSTEM_PROMPT.format(resource_context=context)


def render_read_tool_user_prompt(message: str, intent: str, entry_date: str) -> str:
    return READ_TOOL_USER_PROMPT.format(message=message, intent=intent, entry_date=entry_date)
