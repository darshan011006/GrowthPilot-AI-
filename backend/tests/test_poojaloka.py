"""Primary demo: Poojaloka (real catalogue snapshot) through the full agentic workflow, via the HTTP API."""

from __future__ import annotations

from growthpilot.demo.fixtures import DEMO_GOAL, EVAL_GOAL, SEVEN_PLATFORM_GOAL

from .conftest import run_worker


def _run(api, goal):
    r = api.post("/api/agent/runs", json={"goal": goal})
    assert r.status_code == 200, r.text
    run_worker()
    return api.get(f"/api/agent/runs/{r.json()['id']}").json()


def test_poojaloka_campaign_end_to_end(poojaloka_seeded):
    api = poojaloka_seeded
    brand = api.get("/api/brand").json()
    assert brand["brand"]["name"] == "Poojaloka" and not brand["brand"]["is_synthetic"]
    assert brand["brand"]["catalogue_source"]["snapshot"] is True
    assert any(p["source_url"].startswith("https://poojaloka.com/product/") for p in brand["products"])

    run = _run(api, DEMO_GOAL)
    assert run["status"] == "awaiting_approval", (run.get("outcome_summary"), run.get("error"),
                                                  [(s["tool"], s["status"], s["message"][:120]) for s in run["steps"]])
    steps = run["steps"]
    tools = [s["tool"] for s in steps if s["phase"] == "tool"]
    for t in ("inspect_brand", "retrieve_catalogue", "verify_product_facts", "analyse_trends",
              "collect_competitor_references", "analyse_campaign_history", "identify_content_gaps",
              "create_campaign_plan", "rank_campaign_ideas", "estimate_campaign_cost", "check_platform_capabilities",
              "prepare_schedule", "create_content_brief", "generate_caption", "generate_creative_asset",
              "validate_creative", "create_platform_variant", "request_human_approval"):
        assert t in tools, t
    # Delegation to specialist roles is visible, and each tool step names its role and effect.
    assert {s["role"] for s in steps if s["phase"] == "tool"} >= {"research", "strategy", "creative", "verification",
                                                                  "distribution", "analyst"}
    assert any(s["phase"] == "delegate" for s in steps)
    assert all(s["effect"] for s in steps if s["phase"] == "tool" and s["tool"])
    # Real branching: live search blocked in demo → replan; the offer post fails verification → revised.
    assert next(s for s in steps if s["tool"] == "search_web")["status"] == "blocked"
    assert any(s["phase"] == "replan" for s in steps)
    assert any(s["tool"] == "generate_caption" and (s["input"] or {}).get("revise") for s in steps), \
        "expected a verification-driven revision"
    # Catalogue verification excluded bad listings (the store's test listing and a ₹1 price).
    cat = next(s for s in steps if s["tool"] == "verify_product_facts" and s["input"]["scope"] == "catalogue")
    assert cat["output"]["no_photos"] >= 1

    out = run["outputs"]
    assert out["campaign_id"] and out["content_ids"] and out["variant_ids"] and out["asset_ids"]
    camp = api.get(f"/api/campaigns/{out['campaign_id']}").json()
    plats = {i["platform"] for i in camp["items"]}
    assert plats == {"instagram", "facebook", "pinterest", "threads"}
    assert camp["campaign"]["objective_metric"] == "saves_per_reach" and camp["campaign"]["channel_mix"]

    # Real image files were rendered at each platform's size, with provenance and checks.
    assets = api.get("/api/assets?source=rendered").json()
    assert assets
    sizes = {(a["platform"], a["width"], a["height"]) for a in assets}
    assert ("instagram", 1080, 1350) in sizes and ("pinterest", 1000, 1500) in sizes
    one = api.get(f"/api/assets/{assets[0]['id']}").json()
    assert one["meta"]["checks"] and one["meta"]["photo_kind"] in ("none", "stock_photo", "product_photo")
    assert one["meta"]["photo_kind"] != "stock_photo" or one["meta"]["photo_asset_id"] is None
    f = api.get(f"/api/assets/{assets[0]['id']}/file?format=png&download=1")
    assert f.status_code == 200 and f.content[:8] == b"\x89PNG\r\n\x1a\n"

    inbox = api.get("/api/approvals").json()
    assert inbox["items"]
    for item in inbox["items"]:
        assert item["validation"]["ok"], item["validation"]
    # Approve everything that's waiting (acknowledging warnings such as snapshot price age).
    for item in inbox["items"]:
        r = api.post(f"/api/content/{item['id']}/approve", json={"version": item["version"],
                                                                  "acknowledge_warnings": True})
        assert r.status_code == 200, r.text
    run_worker()
    run = api.get(f"/api/agent/runs/{run['id']}").json()
    assert run["status"] == "completed", run["outcome_summary"]
    sched = [s for s in run["steps"] if s["tool"] == "prepare_schedule" and s["input"].get("commit")][0]
    platforms = {x["platform"] for x in sched["output"]["scheduled"]}
    assert {"instagram", "facebook"} <= platforms

    # Publishing one platform doesn't mark its siblings as published.
    ig = next(x for x in sched["output"]["scheduled"] if x["platform"] == "instagram")
    r = api.post(f"/api/content/{ig['content_id']}/publish-now", json={})
    assert r.status_code == 200 and r.json()["status"] == "published", r.text
    fam = r.json()["family"]
    assert any(f["status"] == "scheduled" for f in fam if f["platform"] != "instagram")


def test_seven_platform_goal_creates_briefs_for_video_only_channels(poojaloka_seeded):
    api = poojaloka_seeded
    run = _run(api, SEVEN_PLATFORM_GOAL)
    assert run["status"] == "awaiting_approval", run.get("outcome_summary")
    camp = api.get(f"/api/campaigns/{run['outputs']['campaign_id']}").json()
    assert {i["platform"] for i in camp["items"]} == {"instagram", "facebook", "pinterest", "x", "linkedin",
                                                      "youtube", "threads"}
    yt = [i for i in camp["items"] if i["platform"] == "youtube"]
    assert yt and all(i["content_type"] == "video" and i["status"] == "draft" for i in yt)
    assert any("YouTube" in s["message"] for s in run["steps"] if s["phase"] == "decision")
    x = [i for i in camp["items"] if i["platform"] == "x"]
    assert all(len(i["caption"]) <= 280 for i in x)


def test_poojaloka_learning_loop(poojaloka_seeded):
    api = poojaloka_seeded
    run = _run(api, EVAL_GOAL)
    assert run["status"] == "completed", run
    exps = api.get("/api/experiments").json()
    hist = next(e for e in exps if "synthetic history" in e["name"])
    assert hist["primary_metric"] == "saves_per_reach"
    assert hist["conclusion"] in ("supported", "inconclusive", "not_supported")
    assert hist["result"]["platform"] == "instagram"
    assert "SYNTHETIC" in hist["learnings"]
    recs = api.get("/api/recommendations").json()
    assert recs and all(r["is_synthetic"] for r in recs)
    change = next((r for r in recs if r["proposed_change"]), None)
    assert change is not None
    r = api.post(f"/api/recommendations/{change['id']}/apply")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"
