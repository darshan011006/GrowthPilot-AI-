"""LLM provider interface. Only Anthropic (Claude) is implemented; demo mode uses no LLM at all."""

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
    name: str

    def structured(self, system: str, prompt: str, schema: type[M]) -> tuple[M, int]:
        """Return a schema-validated object and tokens used."""

    def tool_turn(self, system: str, messages: list[dict], tools: list[dict]) -> tuple[Any, int]:
        """One agent turn with tools. Returns the raw response message and tokens used."""


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
    if not s.llm_configured:
        raise LLMUnavailable("No LLM configured. Set LLM_API_KEY (Anthropic) in .env and restart.")
    from .anthropic_llm import AnthropicLLM

    return AnthropicLLM(api_key=s.llm_key, model=s.llm_model, effort=s.llm_effort)
