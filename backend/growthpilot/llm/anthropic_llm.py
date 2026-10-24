"""Claude via the official Anthropic SDK.

* ``structured`` uses structured outputs (``output_format=<pydantic model>``) so responses are schema-validated.
* ``tool_turn`` runs one turn of the agent loop with our typed tools (tool_choice auto; the model picks).
* Both opt into the server-side refusal fallback (``fallbacks="default"``) so a safety decline is retried
  on Anthropic's recommended fallback model rather than failing outright.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from .. import usage
from ..security import redact
from . import LLMError, strip_provider_fields

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _io(u: Any) -> tuple[int, int]:
    return int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str, client: anthropic.Anthropic | None = None):
        self.model = model
        self.effort = effort
        self.name = f"claude:{model}"
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=2)

    def _guard(self, fn):
        try:
            return fn()
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic rejected the API key. Check LLM_API_KEY.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("This API key can't use the configured model or feature.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Model {self.model!r} was not found. Check LLM_MODEL.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic rate limit reached.", retryable=True) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Anthropic rejected the request: {redact(exc.message)}") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMError("The model call timed out.", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error ({exc.status_code}).", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API.", retryable=True) from exc

    @staticmethod
    def _check_stop(response: Any) -> None:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMError(f"The model declined this request (category: {category or 'unspecified'}).")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model's response was cut off (max tokens). Try a smaller request.")

    def _account(self, response: Any, operation: str) -> int:
        i, o = _io(response.usage)
        usage.record(provider="anthropic", operation=operation, model=self.model, input_tokens=i, output_tokens=o)
        return i + o

    def structured(self, system: str, prompt: str, schema: type[M]) -> tuple[M, int]:
        usage.preflight(usage.estimate_llm_call(self.model, len(system) + len(prompt), 8000),
                        f"A Claude call ({schema.__name__})")
        response = self._guard(
            lambda: self._client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        )
        tokens = self._account(response, f"structured:{schema.__name__}")
        self._check_stop(response)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("The model returned output that didn't match the expected schema.", retryable=True)
        log.info("llm structured model=%s request_id=%s", response.model, response._request_id)
        return parsed, tokens

    def tool_turn(self, system: str, messages: list[dict], tools: list[dict]) -> tuple[Any, int]:
        messages = strip_provider_fields(messages)
        usage.preflight(usage.estimate_llm_call(self.model, len(system) + len(str(messages)) + len(str(tools)), 8000),
                        "A Claude planning turn")
        response = self._guard(
            lambda: self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=messages,
                tools=tools,
                tool_choice={"type": "auto"},
                output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        )
        tokens = self._account(response, "tool_turn")
        if response.stop_reason == "refusal":
            self._check_stop(response)
        log.info("llm tool_turn model=%s request_id=%s stop=%s", response.model, response._request_id,
                 response.stop_reason)
        return response, tokens
