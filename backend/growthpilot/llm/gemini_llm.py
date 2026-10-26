"""Google Gemini via the Interactions API (REST, server-side).

Implemented from Google's documentation (checked 2026-10-24):
  * Endpoint:  POST https://generativelanguage.googleapis.com/v1beta/interactions, header ``x-goog-api-key``
  * Stateless: ``store: false`` and the full history in ``input`` as steps (``user_input``, the model's own
               steps exactly as received — including ``thought`` steps that carry signatures — and
               ``function_result`` steps with ``call_id``).
  * Tools:     ``[{"type": "function", "name", "description", "parameters": <JSON schema>}]``
  * JSON:      ``response_format: {"type": "text", "mime_type": "application/json", "schema": ...}``
  * Thinking:  ``generation_config.thinking_level`` (minimal/low/medium/high; support varies by model)
  * Result:    ``status`` (completed | requires_action | incomplete | failed …), ``steps`` (model_output with
               text content, function_call with id/name/arguments), ``usage.total_input_tokens`` /
               ``total_output_tokens`` / ``total_thought_tokens``.

Status: implemented and tested against a mocked API; verify with a real key using the Integrations page.
"""

from __future__ import annotations

import copy
import json
import logging
from types import SimpleNamespace
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .. import usage
from ..research.net import client
from ..security import redact
from . import LLMError

log = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)

API = "https://generativelanguage.googleapis.com/v1beta"
MAX_OUTPUT_TOKENS = 16000


def inline_schema(schema: dict) -> dict:
    """Resolve local ``$ref``s from Pydantic's ``$defs`` and drop titles (keeps schemas simple for Gemini)."""
    defs = schema.get("$defs", {})

    def walk(node: Any, depth: int = 0, field_names: bool = False) -> Any:
        # field_names: node maps field names to schemas (the value of "properties"), so a field called
        # "title" is data and must be kept; elsewhere "title" is schema metadata and is dropped.
        if depth > 20:
            return {}
        if isinstance(node, dict):
            if field_names:
                return {k: walk(v, depth + 1) for k, v in node.items()}
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                target = copy.deepcopy(defs.get(node["$ref"].split("/")[-1], {}))
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra}, depth + 1)
            return {k: walk(v, depth + 1, field_names=k in ("properties", "patternProperties"))
                    for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(x, depth + 1) for x in node]
        return node

    return walk(schema)


def _text(blocks: Any) -> str:
    if isinstance(blocks, str):
        return blocks
    out = []
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "".join(out)


class GeminiLLM:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, thinking_level: str = "medium"):
        self.model = model
        self.thinking_level = thinking_level
        self.name = f"gemini:{model}"
        self._key = api_key

    # ── HTTP ─────────────────────────────────────────────────────────────
    def _post(self, body: dict, what: str) -> dict:
        try:
            with client(timeout=httpx.Timeout(180.0, connect=10.0),
                        headers={"x-goog-api-key": self._key, "Content-Type": "application/json"}) as c:
                resp = c.post(f"{API}/interactions", json=body)
        except httpx.TimeoutException as exc:
            raise LLMError("The Gemini call timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach the Gemini API ({type(exc).__name__}).", retryable=True) from exc
        if resp.status_code in (401, 403):
            raise LLMError("Gemini rejected the API key (check GEMINI_API_KEY and that the Gemini API is enabled).")
        if resp.status_code == 404:
            raise LLMError(f"Gemini model {self.model!r} was not found. Check GEMINI_MODEL.")
        if resp.status_code == 429:
            msg, delay = self._quota_details(resp)
            if delay > 300 or "per day" in msg.lower():
                # A daily quota (e.g. the free tier's requests-per-day) won't reset within a run's retries.
                raise LLMError(f"Gemini's daily request limit is used up. {msg} Enable billing on the Google "
                               "project for higher limits, or try again later.".replace("  ", " "))
            raise LLMError("Gemini rate limit or quota reached." + (f" {msg}" if msg else ""), retryable=True)
        if resp.status_code >= 500:
            raise LLMError(f"Gemini API error (HTTP {resp.status_code}).", retryable=True)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except ValueError:
                msg = resp.text[:200]
            raise LLMError(f"Gemini rejected the {what} request: {redact(str(msg))[:300]}")
        data = resp.json()
        status = data.get("status")
        if status == "failed":
            errs = "; ".join(str(e.get("message", "")) for e in data.get("errors") or [])[:300]
            raise LLMError(f"The Gemini interaction failed: {redact(errs) or 'no detail'}", retryable=True)
        if status == "incomplete":
            raise LLMError("The Gemini response was cut off (output limit). Try a smaller request.")
        return data

    def _quota_details(self, resp: httpx.Response) -> tuple[str, float]:
        """Google's own explanation of a 429 (key removed) and its suggested retry delay in seconds."""
        try:
            err = resp.json().get("error", {}) or {}
        except ValueError:
            return "", 0.0
        msg = redact(str(err.get("message", ""))).replace(self._key, "[redacted]")[:300] if self._key else ""
        delay = 0.0
        for d in err.get("details") or []:
            if str(d.get("@type", "")).endswith("RetryInfo"):
                try:
                    delay = float(str(d.get("retryDelay", "0")).rstrip("s") or 0)
                except ValueError:
                    pass
        return msg, delay

    def _account(self, data: dict, operation: str) -> int:
        u = data.get("usage") or {}
        i = int(u.get("total_input_tokens") or 0) + int(u.get("total_tool_use_tokens") or 0)
        o = int(u.get("total_output_tokens") or 0) + int(u.get("total_thought_tokens") or 0)
        usage.record(provider="gemini", operation=operation, model=self.model, input_tokens=i, output_tokens=o)
        return i + o

    def _config(self) -> dict:
        return {"thinking_level": self.thinking_level, "max_output_tokens": MAX_OUTPUT_TOKENS}

    # ── structured output ────────────────────────────────────────────────
    def structured(self, system: str, prompt: str, schema: type[M]) -> tuple[M, int]:
        usage.preflight(usage.estimate_llm_call(self.model, len(system) + len(prompt), 8000),
                        f"A Gemini call ({schema.__name__})")
        body = {"model": self.model, "store": False, "system_instruction": system,
                "input": [{"type": "user_input", "content": [{"type": "text", "text": prompt}]}],
                "response_format": {"type": "text", "mime_type": "application/json",
                                    "schema": inline_schema(schema.model_json_schema())},
                "generation_config": self._config()}
        data = self._post(body, "structured output")
        tokens = self._account(data, f"structured:{schema.__name__}")
        text = "".join(_text(s.get("content")) for s in data.get("steps") or [] if s.get("type") == "model_output")
        try:
            return schema.model_validate_json(text), tokens
        except ValidationError as exc:
            log.info("gemini structured output failed validation: %s", exc.errors()[:3])
            raise LLMError("The model returned output that didn't match the expected schema.", retryable=True) from exc

    # ── tool use ─────────────────────────────────────────────────────────
    @staticmethod
    def _steps(messages: list[dict]) -> list[dict]:
        names: dict[str, str] = {}
        steps: list[dict] = []
        for m in messages:
            content = m.get("content")
            if m.get("role") == "assistant":
                raw = m.get("raw_steps")
                if raw is None:  # history written by another provider: translate it
                    raw = []
                    for b in content or []:
                        if b.get("type") == "text" and b.get("text"):
                            raw.append({"type": "model_output", "content": [{"type": "text", "text": b["text"]}]})
                        elif b.get("type") == "tool_use":
                            raw.append({"type": "function_call", "id": b["id"], "name": b["name"],
                                        "arguments": b.get("input") or {}})
                for st in raw:
                    if st.get("type") == "function_call":
                        names[st.get("id", "")] = st.get("name", "")
                steps.extend(raw)
                continue
            if isinstance(content, str):
                steps.append({"type": "user_input", "content": [{"type": "text", "text": content}]})
                continue
            texts = []
            for b in content or []:
                if b.get("type") == "tool_result":
                    cid = b.get("tool_use_id", "")
                    step = {"type": "function_result", "call_id": cid, "name": names.get(cid, ""),
                            "result": [{"type": "text", "text": str(b.get("content", ""))}]}
                    if b.get("is_error"):
                        step["is_error"] = True
                    steps.append(step)
                elif b.get("type") == "text":
                    texts.append(b.get("text", ""))
            if texts:
                steps.append({"type": "user_input", "content": [{"type": "text", "text": "\n\n".join(texts)}]})
        return steps

    def tool_turn(self, system: str, messages: list[dict], tools: list[dict]) -> tuple[Any, int]:
        decls = [{"type": "function", "name": t["name"], "description": t["description"],
                  "parameters": inline_schema(t["input_schema"])} for t in tools]
        steps = self._steps(messages)
        usage.preflight(usage.estimate_llm_call(self.model, len(system) + len(json.dumps(steps)) + len(json.dumps(decls)),
                                                8000), "A Gemini planning turn")
        body = {"model": self.model, "store": False, "system_instruction": system, "input": steps, "tools": decls,
                "generation_config": self._config() | {"tool_choice": "auto"}}
        data = self._post(body, "planning")
        tokens = self._account(data, "tool_turn")
        out_steps = data.get("steps") or []
        content: list[dict] = []
        for st in out_steps:
            if st.get("type") == "model_output":
                t = _text(st.get("content"))
                if t.strip():
                    content.append({"type": "text", "text": t})
            elif st.get("type") == "function_call":
                content.append({"type": "tool_use", "id": str(st.get("id") or ""), "name": st.get("name", ""),
                                "input": st.get("arguments") or {}})
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        log.info("gemini tool_turn model=%s status=%s calls=%d", self.model, data.get("status"),
                 sum(1 for b in content if b["type"] == "tool_use"))
        return SimpleNamespace(content=content, stop_reason=stop, raw_steps=out_steps), tokens


def check_key(api_key: str, model: str) -> tuple[bool, str]:
    """Minimal, free connection test: look the model up (models.get)."""
    try:
        with client(headers={"x-goog-api-key": api_key}) as c:
            resp = c.get(f"{API}/models/{model}")
    except httpx.HTTPError as exc:
        return False, f"Could not reach the Gemini API ({type(exc).__name__})."
    if resp.status_code in (401, 403):
        return False, "Gemini rejected the API key."
    if resp.status_code == 404:
        return False, f"Model {model} is not available to this key."
    if resp.status_code >= 400:
        return False, f"Gemini returned HTTP {resp.status_code}."
    name = (resp.json() or {}).get("displayName") or model
    return True, f"Key works and {name} is available."
