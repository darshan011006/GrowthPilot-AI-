"""LLM provider interface.

Two providers are implemented behind one interface: Google Gemini (Interactions API) and Anthropic Claude
(Messages API). Demo mode uses no LLM at all. Every call goes through ``usage.preflight`` (budget check) and
``usage.record`` (cost estimate), so the orchestrator never needs provider-specific code.

The conversation format used by the agent planner is provider-neutral and Anthropic-shaped:
``{"role": "user"|"assistant", "content": str | [blocks]}`` with ``text``, ``tool_use`` and ``tool_result``
blocks. Providers translate it; provider-specific data that must be replayed verbatim (Gemini thought
signatures) is kept on the assistant message under ``raw_steps`` and stripped before other providers see it.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from ..config import get_settings

M = TypeVar("M", bound=BaseModel)


class LLMError(RuntimeError):
    """Model call failed. Message is safe to show users."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMUnavailable(LLMError):
    pass


class LLM(Protocol):
    name: str  # "<provider>:<model>"
    provider: str
    model: str

    def structured(self, system: str, prompt: str, schema: type[M]) -> tuple[M, int]:
        """Return a schema-validated object and tokens used."""

    def tool_turn(self, system: str, messages: list[dict], tools: list[dict]) -> tuple[Any, int]:
        """One agent turn with tools. Returns a response with ``content`` blocks and ``stop_reason``."""


_override: LLM | None = None


def set_llm_override(llm: LLM | None) -> None:
    """Tests inject a fake LLM here."""
    global _override
    _override = llm


def get_llm() -> LLM | None:
    """The configured LLM, or None in demo mode. Raises LLMUnavailable in live mode without a key."""
    if _override is not None:
        return _override
    s = get_settings()
    if s.is_demo:
        return None
    provider = s.active_llm_provider
    if provider == "gemini":
        from .gemini_llm import GeminiLLM

        return GeminiLLM(api_key=s.gemini_api_key, model=s.gemini_model, thinking_level=s.gemini_thinking_level)
    if provider == "anthropic":
        from .anthropic_llm import AnthropicLLM

        return AnthropicLLM(api_key=s.llm_key, model=s.llm_model, effort=s.llm_effort)
    raise LLMUnavailable("No LLM configured. Set GEMINI_API_KEY (or LLM_API_KEY for Anthropic) in .env and restart.")


def strip_provider_fields(messages: list[dict]) -> list[dict]:
    """Remove keys that only one provider understands before sending messages to another."""
    return [{k: v for k, v in m.items() if k in ("role", "content")} for m in messages]
