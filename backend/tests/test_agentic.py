"""Run lifecycle: budget approval pauses, pause/resume, retry, crash recovery, non-content approvals, variants,
partial publication failures and approval invalidation."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from growthpilot import usage
from growthpilot.agent.planner_llm import LLMPlanner
from growthpilot.agent.runner import Runner, create_run, execute_run, recover_stale
from growthpilot.db import session_scope
from growthpilot.demo.fixtures import DEMO_GOAL
from growthpilot.llm import set_llm_override
from growthpilot.models import AgentRun, ApprovalRequest, ChannelConnection, Workspace, utcnow
from growthpilot.research import net

from .conftest import Api, make_client, run_worker
from .test_agent import Block, Resp


def _run_id(goal: str, user_id: int = 1) -> str:
    with session_scope() as db:
        ws = db.execute(select(Workspace)).scalars().first()
        return create_run(db, workspace_id=ws.id, user_id=user_id, goal=goal).id


class ChargingLLM:
    """Scripted model whose planning turns cost money, to exercise the budget gate."""

    name = "fake-charging"
    provider = "fake"
    model = "claude-opus-5-5"

    def __init__(self, script, cost: float):
        self.script = list(script)
        self.cost = cost

    def tool_turn(self, system, messages, tools):
        usage.preflight(self.cost, "A planning turn")
        usage.record(provider="fake", operation="tool_turn", model=self.model, cost_usd=self.cost)
        return self.script.pop(0), 10

    def structured(self, system, prompt, schema):
        raise AssertionError("not used")


def _live(monkeypatch, tmp_path):
    api = Api(make_client(monkeypatch, tmp_path, "live", LLM_API_KEY="test"))
    api.register()
    api.put("/api/brand", json={"name": "Live Brand", "location": "Bengaluru"})
    net.set_resolver(lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", 443))])
    return api


def test_budget_gate_pauses_for_owner_approval_then_continues(monkeypatch, tmp_path):
    api = _live(monkeypatch, tmp_path)
    set_llm_override(ChargingLLM([
        Resp([Block("text", "Plan: inspect the brand."), Block("tool_use", id="t1", name="inspect_brand")], "tool_use"),
        Resp([Block("text", "Done.")], "end_turn"),
    ], cost=0.40))
    r = api.post("/api/agent/runs", json={"goal": "Inspect the brand"}).json()
    run_worker()
    run = api.get(f"/api/agent/runs/{r['id']}").json()
    # First turn ($0.40) exceeds the $0.25 single-operation threshold → owner approval needed before spending.
    assert run["status"] == "awaiting_approval", run
    reqs = api.get("/api/approval-requests").json()
    assert len(reqs) == 1 and reqs[0]["kind"] == "budget" and reqs[0]["payload"]["needed_usd"] == 0.4
    assert api.get("/api/usage").json()["month_cost_usd"] == 0  # nothing was spent while waiting
    d = api.post(f"/api/approval-requests/{reqs[0]['id']}/decide", json={"approve": True})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    run_worker()
    run = api.get(f"/api/agent/runs/{r['id']}").json()
    assert run["status"] == "completed", run
    assert run["cost_usd"] > 0.4  # both turns charged after approval
    u = api.get(f"/api/agent/runs/{r['id']}/usage").json()
    assert len(u["records"]) == 2 and u["approval_requests"][0]["status"] == "approved"


def test_declined_budget_continues_without_the_paid_step(poojaloka_seeded):
    api = poojaloka_seeded
    rid = _run_id(DEMO_GOAL)
    with session_scope() as db:
        run = db.get(AgentRun, rid)
        r = Runner(db, run)
        run.status = "awaiting_approval"
        r.ctx.remember("budget_block", {"tool": "search_web", "needed_usd": 0.01, "message": "x"})
        r.ctx.remember("need_budget", True)
        req = ApprovalRequest(workspace_id=run.workspace_id, run_id=run.id, kind="budget", title="t",
                              payload={"needed_usd": 0.01})
        db.add(req)
        db.flush()
        rid_req = req.id
    d = api.post(f"/api/approval-requests/{rid_req}/decide", json={"approve": False, "note": "not now"})
    assert d.status_code == 200 and d.json()["status"] == "rejected"
    with session_scope() as db:
        run = db.get(AgentRun, rid)
        assert run.status == "queued" and not run.state.get("need_budget")


def test_pause_and_resume_keep_completed_work(poojaloka_seeded):
    api = poojaloka_seeded
    r = api.post("/api/agent/runs", json={"goal": "Research Deepavali trends for pooja essentials"}).json()
    p = api.post(f"/api/agent/runs/{r['id']}/pause")
    assert p.status_code == 200 and p.json()["status"] == "paused"
    run_worker()
    assert api.get(f"/api/agent/runs/{r['id']}").json()["status"] == "paused"  # the worker leaves it alone
    # Pause while running: the runner stops at the next step boundary.
    with session_scope() as db:
        run = db.get(AgentRun, r["id"])
        run.status, run.pause_requested = "queued", True
    with session_scope() as db:
        execute_run(db, db.get(AgentRun, r["id"]))
    run = api.get(f"/api/agent/runs/{r['id']}").json()
    assert run["status"] == "paused" and any("Paused" in s["message"] for s in run["steps"])
    assert api.post(f"/api/agent/runs/{r['id']}/unpause").json()["status"] == "queued"
    run_worker()
    run = api.get(f"/api/agent/runs/{r['id']}").json()
    assert run["status"] == "completed", run["outcome_summary"]
    assert sum(1 for s in run["steps"] if s["tool"] == "inspect_brand") == 1


def test_retry_continues_a_blocked_run(demo):
    api = demo
    r = api.post("/api/agent/runs", json={"goal": "Research Deepavali trends"}).json()
    run_worker()
    run = api.get(f"/api/agent/runs/{r['id']}").json()
    assert run["status"] == "blocked" and "brand_missing" in run["blockers"]
    api.put("/api/brand", json={"name": "New Brand", "location": "Bengaluru"})
    api.post("/api/products", json={"sku": "D1", "name": "Clay Diya", "category": "Mud Items", "price": "125"})
    assert api.post(f"/api/agent/runs/{r['id']}/retry").json()["status"] == "queued"
    run_worker()
    run = api.get(f"/api/agent/runs/{r['id']}").json()
    assert run["status"] == "completed", run["outcome_summary"]
    assert any(s["phase"] == "replan" and "Retry" in s["message"] for s in run["steps"])


def test_crash_recovery_resumes_without_redoing_steps(poojaloka_seeded):
    rid = _run_id(DEMO_GOAL)
    with session_scope() as db:
        db.get(AgentRun, rid).max_steps = 6
    with session_scope() as db:
        execute_run(db, db.get(AgentRun, rid))
    with session_scope() as db:  # pretend the worker died mid-run
        run = db.get(AgentRun, rid)
        done_before = sum(1 for s in run.plan if s["status"] == "done")
        run.status, run.finished_at, run.max_steps = "running", None, 80
        run.heartbeat_at = utcnow() - timedelta(minutes=30)
    with session_scope() as db:
        recover_stale(db)
        run = db.get(AgentRun, rid)
        assert run.status == "queued" and run.recoveries == 1
    run_worker()
    with session_scope() as db:
        run = db.get(AgentRun, rid)
        assert run.status == "awaiting_approval", run.outcome_summary
        tools = [s.tool for s in run.steps if s.phase == "tool"]
        assert tools.count("inspect_brand") == 1 and tools.count("retrieve_catalogue") == 1
        assert done_before >= 3
        assert any("Recovered" in s.message for s in run.steps)


def test_llm_recovery_reports_interrupted_tool_call(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    rid = _run_id("Inspect the brand")
    with session_scope() as db:
        run = db.get(AgentRun, rid)
        ctx = Runner.__new__(Runner)
        ctx.db = db
        from growthpilot.agent.registry import ToolContext
        from growthpilot.config import get_settings

        tc = ToolContext(db=db, run=run, workspace_id=run.workspace_id, brand_id=run.brand_id, settings=get_settings(),
                         user_role="owner")
        tc.remember("messages", [{"role": "user", "content": "goal"},
                                 {"role": "assistant", "content": [{"type": "tool_use", "id": "t9",
                                                                    "name": "inspect_brand", "input": {}}]}])
        tc.remember("current_call", {"id": "t9", "name": "inspect_brand", "input": {}})
        tc.remember("pending_results", [])
        LLMPlanner(ChargingLLM([], 0)).recover(tc)
        pending = run.state["pending_results"]
        assert pending and pending[0]["tool_use_id"] == "t9" and pending[0]["is_error"]


def test_strategy_change_request_pauses_until_decided(monkeypatch, tmp_path):
    api = _live(monkeypatch, tmp_path)
    set_llm_override(ChargingLLM([
        Resp([Block("text", "I propose shifting posts to Pinterest; asking first."),
              Block("tool_use", id="t1", name="request_human_approval",
                    input={"kind": "strategy_change", "title": "Shift 20% of posts to Pinterest",
                           "detail": "Pinterest saves look stronger."})], "tool_use"),
        Resp([Block("text", "Approved; noted for the next plan.")], "end_turn"),
    ], cost=0.0))
    r = api.post("/api/agent/runs", json={"goal": "Review the channel mix"}).json()
    run_worker()
    assert api.get(f"/api/agent/runs/{r['id']}").json()["status"] == "awaiting_approval"
    inbox = api.get("/api/approvals").json()
    req = next(q for q in inbox["requests"] if q["kind"] == "strategy_change")
    api.post(f"/api/approval-requests/{req['id']}/decide", json={"approve": True})
    run_worker()
    assert api.get(f"/api/agent/runs/{r['id']}").json()["status"] == "completed"


def _master_with_variant(api) -> tuple[dict, dict]:
    prods = api.get("/api/products").json()
    p = next(x for x in prods if x["name"].startswith("Matki Diya"))
    item = api.post("/api/content", json={"hook": "Clay diyas for Deepavali", "caption": f"{p['name']} · Mud Items.",
                                          "cta": "View the product", "hashtags": ["#Poojaloka"],
                                          "product_ids": [p["id"]], "content_type": "post"}).json()
    item = api.post(f"/api/content/{item['id']}/creative", json={}).json()
    assert item["assets"][0]["source"] == "rendered" and item["assets"][0]["width"] == 1080
    out = api.post(f"/api/content/{item['id']}/variants", json={"platforms": ["facebook"]}).json()
    fb = api.get(f"/api/content/{out['created'][0]}").json()
    assert fb["master_id"] == item["id"] and fb["assets"][0]["meta"]["platform"] == "facebook"
    return api.get(f"/api/content/{item['id']}").json(), fb


def _approve(api, item):
    api.post(f"/api/content/{item['id']}/submit")
    item = api.get(f"/api/content/{item['id']}").json()
    r = api.post(f"/api/content/{item['id']}/approve", json={"version": item["version"], "acknowledge_warnings": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_regenerating_one_variant_leaves_siblings_alone(poojaloka_seeded):
    api = poojaloka_seeded
    ig, fb = _master_with_variant(api)
    ig = _approve(api, ig)
    r = api.post(f"/api/content/{fb['id']}/regenerate", json={})
    assert r.status_code == 200, r.text
    assert r.json()["version"] >= fb["version"]
    again = api.get(f"/api/content/{ig['id']}").json()
    assert again["status"] == "approved" and again["version"] == ig["version"] and again["approval_intact"]


def test_rerender_invalidates_approval(poojaloka_seeded):
    api = poojaloka_seeded
    ig, _ = _master_with_variant(api)
    ig = _approve(api, ig)
    r = api.post(f"/api/content/{ig['id']}/creative", json={"variation": 1}).json()
    assert r["status"] == "draft" and r["approved_version"] is None and r["version"] == ig["version"] + 1


def test_partial_publication_failure_is_tracked_per_platform(poojaloka_seeded):
    api = poojaloka_seeded
    ig, fb = _master_with_variant(api)
    ig, fb = _approve(api, ig), _approve(api, fb)
    conns = {c["platform"]: c["id"] for c in api.get("/api/integrations").json()["connections"]}
    for item in (ig, fb):
        r = api.post(f"/api/content/{item['id']}/schedule", json={"connection_id": conns[item["platform"]]})
        assert r.status_code == 200, r.text
    with session_scope() as db:
        db.get(ChannelConnection, conns["facebook"]).config = {"simulate_failure": True}
    assert api.post(f"/api/content/{ig['id']}/publish-now", json={}).json()["status"] == "published"
    fb_after = api.post(f"/api/content/{fb['id']}/publish-now", json={}).json()
    assert fb_after["status"] == "failed" and "outage" in fb_after["last_error"]
    assert fb_after["attempts"][0]["success"] is False
    family = {f["platform"]: f["status"] for f in fb_after["family"]}
    assert family == {"instagram": "published", "facebook": "failed"}


def test_asset_library_and_downloads(poojaloka_seeded):
    api = poojaloka_seeded
    ig, _ = _master_with_variant(api)
    lib = api.get("/api/assets?source=rendered&platform=facebook").json()
    assert lib and all(a["platform"] == "facebook" for a in lib)
    a = api.get(f"/api/assets/{ig['asset_id']}").json()
    assert a["meta"]["photo_kind"] in ("none", "stock_photo") and a["meta"]["photo_asset_id"] is None
    assert "typographic product card" in json.dumps(a["meta"]["notes"])
    jpg = api.get(f"/api/assets/{ig['asset_id']}/file?download=1")
    assert jpg.status_code == 200 and jpg.content[:3] == b"\xff\xd8\xff" and "attachment" in jpg.headers[
        "content-disposition"]
