"""Regression: the fictional Aranya furniture brand through the whole workflow (Instagram only), via the HTTP API."""

from __future__ import annotations

from growthpilot.demo.fixtures import ARANYA_EVAL_GOAL as EVAL_GOAL
from growthpilot.demo.fixtures import ARANYA_GOAL as DEMO_GOAL

from .conftest import run_worker


def _start(api, goal):
    r = api.post("/api/agent/runs", json={"goal": goal})
    assert r.status_code == 200, r.text
    run_worker()
    return api.get(f"/api/agent/runs/{r.json()['id']}").json()


def test_full_campaign_flow(demo_seeded):
    api = demo_seeded
    run = _start(api, DEMO_GOAL)
    assert run["status"] == "awaiting_approval", run.get("outcome_summary") or run.get("error")
    tools = [s["tool"] for s in run["steps"] if s["phase"] == "tool"]
    phases = [s["phase"] for s in run["steps"]]
    # Real branching: live search is unavailable in demo mode → blocked → replan.
    search = next(s for s in run["steps"] if s["tool"] == "search_web")
    assert search["status"] == "blocked"
    assert "replan" in phases
    for t in ("inspect_brand", "retrieve_catalogue", "analyse_trends", "collect_competitor_references",
              "identify_content_gaps", "create_campaign_plan", "rank_campaign_ideas", "prepare_schedule",
              "generate_caption", "generate_creative_asset", "verify_product_facts", "validate_creative",
              "request_human_approval"):
        assert t in tools, t
    # The festive post's offer wording fails verification and is revised.
    assert tools.count("verify_product_facts") >= 3
    revise = [s for s in run["steps"] if s["tool"] == "generate_caption" and s["input"].get("revise")]
    assert revise, "expected a revision round"
    # Mock/fixture usage is disclosed on steps.
    assert any(s["is_mock"] for s in run["steps"])

    inbox = api.get("/api/approvals").json()
    assert inbox["items"], "items should be waiting for approval"
    for item in inbox["items"]:
        assert item["validation"]["ok"], item["validation"]
        assert item["status"] == "in_review"
        assert item["campaign"]["objective"]
        assert item["evidence"], "approval card shows supporting evidence"

    # Approve everything (acknowledging warnings such as placeholder images).
    for item in inbox["items"]:
        r = api.post(f"/api/content/{item['id']}/approve", json={"version": item["version"],
                                                                  "acknowledge_warnings": True})
        assert r.status_code == 200, r.text
    run_worker()  # auto-resumed run schedules approved items
    run = api.get(f"/api/agent/runs/{run['id']}").json()
    assert run["status"] == "completed", run
    sched = [s for s in run["steps"] if s["tool"] == "prepare_schedule" and s["input"].get("commit")][0]
    assert sched["output"]["scheduled"]

    # Publish one now via the demo adapter and verify.
    cid = sched["output"]["scheduled"][0]["content_id"]
    r = api.post(f"/api/content/{cid}/publish-now", json={})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["status"] == "published"
    assert item["publish_verified"] is True
    assert item["attempts"][0]["live"] is False
    assert "Simulated" in item["attempts"][0]["summary"]

    # Analytics: synthetic data is labelled as such.
    r = api.post("/api/analytics/collect")
    assert r.status_code == 200
    a = api.get("/api/analytics").json()
    assert a["data_source"] == "synthetic"
    assert "engagement_rate_by_reach" in a["definitions"]


def test_adaptive_loop_evaluates_history(demo_seeded):
    api = demo_seeded
    run = _start(api, EVAL_GOAL)
    assert run["status"] == "completed", run
    tools = [s["tool"] for s in run["steps"] if s["phase"] == "tool"]
    assert "evaluate_experiment" in tools and "recommend_next_action" in tools
    exps = api.get("/api/experiments").json()
    hist = next(e for e in exps if "synthetic history" in e["name"])
    assert hist["conclusion"] in ("supported", "inconclusive", "not_supported")
    assert "SYNTHETIC" in hist["learnings"]
    recs = api.get("/api/recommendations").json()
    assert recs and all(r["is_synthetic"] for r in recs)
    assert any(e["status"] == "planned" for e in exps), "next experiment planned"
    reports = api.get("/api/reports").json()
    assert reports
    body = api.get(f"/api/reports/{reports[0]['id']}").json()["markdown"]
    assert "Demo data notice" in body and "Hypotheses" in body


def test_overview_and_reset(demo_seeded):
    api = demo_seeded
    ov = api.get("/api/overview").json()
    assert ov["mode"] == "demo" and ov["has_brand"]
    assert ov["performance"]["data_source"] == "synthetic"
    r = api.post("/api/demo/reset", json={"confirm": "nope"})
    assert r.status_code == 400
    r = api.post("/api/demo/reset", json={"confirm": "RESET", "brand": "aranya"})
    assert r.status_code == 200
    assert len(api.get("/api/products").json()) == 6
    r = api.post("/api/demo/reset", json={"confirm": "RESET"})
    assert r.status_code == 200 and r.json()["brand"] == "poojaloka"
    assert len(api.get("/api/products").json()) == 40
