"""Gemini, Brave and image-generation providers against mocked APIs; usage, caching, caps and secret handling."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from growthpilot import usage
from growthpilot.db import session_scope
from growthpilot.llm import LLMError
from growthpilot.llm.gemini_llm import GeminiLLM, check_key, inline_schema
from growthpilot.models import CacheEntry, UsageRecord, Workspace
from growthpilot.research import net
from growthpilot.research import search as search_mod

from .conftest import Api, make_client

KEY = "test-gemini-key-not-real"


class Out(BaseModel):
    name: str
    count: int


def _live(monkeypatch, tmp_path, **extra):
    api = Api(make_client(monkeypatch, tmp_path, "live", GEMINI_API_KEY=KEY, BRAVE_SEARCH_API_KEY="brave-key", **extra))
    api.register()
    api.put("/api/brand", json={"name": "Live Brand", "location": "Bengaluru"})
    net.set_resolver(lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", 443))])
    return api


def _scope(db):
    ws = db.execute(select(Workspace)).scalars().first()
    return usage.UsageScope(db=db, workspace_id=ws.id)


def test_gemini_structured_output_records_usage(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    seen = {}

    def handler(req: httpx.Request):
        assert req.url.path == "/v1beta/interactions"
        assert req.headers["x-goog-api-key"] == KEY
        body = json.loads(req.content)
        seen.update(body)
        return httpx.Response(200, json={"status": "completed", "steps": [
            {"type": "thought", "signature": "sig-1"},
            {"type": "model_output", "content": [{"type": "text", "text": '{"name": "diya", "count": 3}'}]}],
            "usage": {"total_input_tokens": 120, "total_output_tokens": 30, "total_thought_tokens": 50}})

    net.set_transport(httpx.MockTransport(handler))
    with session_scope() as db:
        tok = usage.open_scope(_scope(db))
        try:
            out, tokens = GeminiLLM(KEY, "gemini-3.8-flash").structured("sys", "prompt", Out)
        finally:
            usage.close_scope(tok)
        rec = db.execute(select(UsageRecord)).scalars().one()
    assert out.name == "diya" and out.count == 3 and tokens == 200
    assert seen["store"] is False and seen["response_format"]["mime_type"] == "application/json"
    assert "$defs" not in json.dumps(seen["response_format"]["schema"])
    assert rec.provider == "gemini" and rec.input_tokens == 120 and rec.output_tokens == 80 and rec.cost_usd > 0


def test_gemini_tool_turn_replays_thought_signatures(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    calls = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={"status": "requires_action", "steps": [
                {"type": "thought", "signature": "opaque-signature"},
                {"type": "function_call", "id": "fc1", "name": "inspect_brand", "arguments": {}}],
                "usage": {"total_input_tokens": 10, "total_output_tokens": 5}})
        return httpx.Response(200, json={"status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "Done."}]}], "usage": {}})

    net.set_transport(httpx.MockTransport(handler))
    llm = GeminiLLM(KEY, "gemini-3.8-flash")
    tools = [{"name": "inspect_brand", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    resp, _ = llm.tool_turn("sys", [{"role": "user", "content": "goal"}], tools)
    assert resp.stop_reason == "tool_use" and resp.content[0]["name"] == "inspect_brand"
    history = [{"role": "user", "content": "goal"},
               {"role": "assistant", "content": resp.content, "raw_steps": resp.raw_steps},
               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "fc1", "content": "ok"}]}]
    resp2, _ = llm.tool_turn("sys", history, tools)
    assert resp2.stop_reason == "end_turn"
    sent = calls[1]["input"]
    assert {"type": "thought", "signature": "opaque-signature"} in sent  # replayed exactly as received
    fr = next(s for s in sent if s["type"] == "function_result")
    assert fr["call_id"] == "fc1" and fr["name"] == "inspect_brand"
    assert calls[0]["tools"][0]["type"] == "function"


@pytest.mark.parametrize("status,retryable,text", [(401, False, "rejected the API key"), (429, True, "rate limit"),
                                                    (503, True, "API error"), (404, False, "not found")])
def test_gemini_errors_are_mapped_and_never_echo_the_key(monkeypatch, tmp_path, status, retryable, text):
    _live(monkeypatch, tmp_path)
    net.set_transport(httpx.MockTransport(lambda req: httpx.Response(status, json={"error": {"message": f"bad {KEY}"}})))
    with pytest.raises(LLMError) as exc:
        GeminiLLM(KEY, "gemini-3.8-flash").structured("s", "p", Out)
    assert exc.value.retryable is retryable and text in str(exc.value) and KEY not in str(exc.value)


def test_gemini_connection_test(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    net.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json={"displayName": "Gemini 3.8 Flash"})
                                          if req.url.path.endswith("gemini-3.8-flash") else httpx.Response(404)))
    ok, msg = check_key(KEY, "gemini-3.8-flash")
    assert ok and "Gemini 3.8 Flash" in msg
    ok, _ = check_key(KEY, "missing-model")
    assert not ok


def test_inline_schema_resolves_refs():
    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        items: list[Inner]

    s = inline_schema(Outer.model_json_schema())
    assert "$ref" not in json.dumps(s) and s["properties"]["items"]["items"]["properties"]["a"]["type"] == "integer"


def test_brave_cache_caps_and_parallel_search(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    hits = {"n": 0}

    def handler(req: httpx.Request):
        hits["n"] += 1
        assert req.headers["X-Subscription-Token"] == "brave-key"
        q = req.url.params["q"]
        return httpx.Response(200, json={"web": {"results": [{"title": q, "url": f"https://ex.org/{hits['n']}",
                                                              "description": "snippet"}]}})

    net.set_transport(httpx.MockTransport(handler))
    with session_scope() as db:
        ws = db.execute(select(Workspace)).scalars().first()
        ws.search_requests_per_day = 3
        sc = _scope(db)
        tok = usage.open_scope(sc)
        try:
            first = search_mod.search("diya trends")
            second = search_mod.search("diya trends")  # identical → cache, no HTTP request
            assert hits["n"] == 1 and second[0].cached and not first[0].cached
            many = search_mod.search_many(["a", "b", "c"])  # 1 used + 3 requested > cap of 3
            errors = [v for v in many.values() if isinstance(v, Exception)]
            assert len(errors) == 1 and isinstance(errors[0], usage.QuotaExceeded)
            assert hits["n"] == 3
        finally:
            usage.close_scope(tok)
        recs = db.execute(select(UsageRecord).where(UsageRecord.provider == "brave")).scalars().all()
        assert sum(1 for r in recs if r.cached) == 1 and sum(r.cost_usd for r in recs) == pytest.approx(0.015)
        assert db.execute(select(CacheEntry)).scalars().first() is not None


def test_budget_preflight_blocks_paid_calls(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    with session_scope() as db:
        ws = db.execute(select(Workspace)).scalars().first()
        ws.monthly_budget_usd = 0.001
        tok = usage.open_scope(_scope(db))
        try:
            with pytest.raises(usage.BudgetExceeded) as exc:
                usage.preflight(0.01, "A test call")
        finally:
            usage.close_scope(tok)
    assert exc.value.scope == "monthly"


def test_image_background_provider(monkeypatch, tmp_path):
    from PIL import Image

    from growthpilot.creative import imagegen

    _live(monkeypatch, tmp_path, IMAGE_GENERATION_PROVIDER="gemini")
    buf = io.BytesIO()
    Image.new("RGB", (64, 80), (120, 20, 30)).save(buf, "JPEG")
    sent = {}

    def handler(req: httpx.Request):
        sent.update(json.loads(req.content))
        return httpx.Response(200, json={"status": "completed", "steps": [{"type": "model_output", "content": [
            {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}]}]})

    net.set_transport(httpx.MockTransport(handler))
    with session_scope() as db:
        tok = usage.open_scope(_scope(db))
        try:
            data, ctype, info = imagegen.generate_background("Deepavali", ["#6B1420"], 1080, 1350)
        finally:
            usage.close_scope(tok)
        rec = db.execute(select(UsageRecord)).scalars().one()
    assert data[:3] == b"\xff\xd8\xff" and ctype == "image/jpeg" and rec.provider == "gemini-image"
    assert sent["response_format"]["aspect_ratio"] == "4:5"
    assert "no deities" in sent["input"][0]["text"] and "no products" in sent["input"][0]["text"]


def test_integrations_page_lists_seven_platforms_and_tests_keys(monkeypatch, tmp_path):
    api = _live(monkeypatch, tmp_path)
    data = api.get("/api/integrations").json()
    assert [p["key"] for p in data["platforms"]] == ["instagram", "facebook", "pinterest", "x", "linkedin", "youtube",
                                                     "threads"]
    status = {p["key"]: p["status"] for p in data["platforms"]}
    assert status["pinterest"] == "not_implemented" and status["instagram"] == "not_configured"
    gem = next(c for c in data["ai"] if c["key"] == "gemini")
    assert gem["active"] and gem["status"] == "configured"
    assert KEY not in json.dumps(data) and "brave-key" not in json.dumps(data)
    net.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json={"displayName": "Gemini"})))
    r = api.post("/api/integrations/gemini/test").json()
    assert r["ok"] and KEY not in json.dumps(r)
