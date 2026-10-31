"""A brand that moves off Poojaloka must never use Poojaloka catalogue rows, even rows stored before the website
guard existed (Sourcery review on PR #3: agents' catalogue tools, rendering, regeneration and variants)."""

from __future__ import annotations

from sqlalchemy import select

from growthpilot import catalogue
from growthpilot.agent.registry import ToolContext
from growthpilot.agent.runner import create_run
from growthpilot.agent.tools.research import CatalogueIn, retrieve_catalogue
from growthpilot.agent.tools.verification import VerifyIn, verify_product_facts
from growthpilot.api.routes import content as content_routes
from growthpilot.config import get_settings
from growthpilot.db import session_scope
from growthpilot.models import AgentRun, Brand, Product, Workspace


def _post_with_product(api) -> tuple[dict, dict]:
    prods = api.get("/api/products").json()
    p = next(x for x in prods if x["name"].startswith("Matki Diya"))
    item = api.post("/api/content", json={"hook": "Clay diyas", "caption": f"{p['name']} · Mud Items.",
                                          "cta": "View the product", "product_ids": [p["id"]],
                                          "content_type": "post"}).json()
    return item, p


def _move_off_poojaloka_without_cleanup() -> None:
    """The state left by a website change made before the guard: connector cleared, rows still active."""
    with session_scope() as db:
        b = db.execute(select(Brand)).scalars().first()
        b.name, b.website, b.catalogue_source = "SNITCH", "https://www.snitch.com", {}


def _ctx(db) -> ToolContext:
    ws = db.execute(select(Workspace)).scalars().first()
    run = db.get(AgentRun, create_run(db, workspace_id=ws.id, user_id=1, goal="Plan a week of posts").id)
    return ToolContext(db=db, run=run, workspace_id=run.workspace_id, brand_id=run.brand_id, settings=get_settings(),
                       user_role="owner")


def test_poojaloka_rows_are_foreign_only_to_other_brands(poojaloka_seeded):
    with session_scope() as db:
        b = db.execute(select(Brand)).scalars().first()
        p = db.execute(select(Product).where(Product.brand_id == b.id)).scalars().first()
        assert p.source_url.startswith("https://poojaloka.com/")
        assert catalogue.usable_for_brand(b, p) and not catalogue.foreign_store_product(b, p)
        b.website = "https://www.snitch.com"
        assert catalogue.foreign_store_product(b, p) and not catalogue.usable_for_brand(b, p)
        assert catalogue.usable_products(db, b) == []
        manual = Product(workspace_id=b.workspace_id, brand_id=b.id, sku="tee-1", name="Oversized Tee",
                         category="T-Shirts")
        db.add(manual)
        db.flush()
        assert catalogue.usable_products(db, b) == [manual]  # the brand's own rows are unaffected


def test_agent_catalogue_tools_ignore_stale_poojaloka_rows(poojaloka_seeded):
    with session_scope() as db:
        ids = [p.id for p in db.execute(select(Product)).scalars()][:3]
    _move_off_poojaloka_without_cleanup()
    with session_scope() as db:
        ctx = _ctx(db)
        assert retrieve_catalogue(ctx, CatalogueIn(query="diya")).summary == "The catalogue is empty."
        res = verify_product_facts(ctx, VerifyIn(scope="catalogue", product_ids=ids))
        assert res.output["usable"] == [] and len(res.output["excluded"]) == 3
        assert all("another store" in e["reason"] for e in res.output["excluded"])


def test_saving_the_brand_and_startup_archive_stale_rows(poojaloka_seeded, monkeypatch, tmp_path):
    api = poojaloka_seeded
    _move_off_poojaloka_without_cleanup()
    with session_scope() as db:
        assert db.execute(select(Product).where(Product.is_active.is_(True))).scalars().first() is not None
        assert catalogue.archive_foreign_products_everywhere(db) > 0  # what app startup runs
        assert db.execute(select(Product).where(Product.is_active.is_(True))).scalars().first() is None
        for p in db.execute(select(Product)).scalars():
            p.is_active = True
    brand = api.get("/api/brand").json()["brand"]
    r = api.put("/api/brand", json={k: brand[k] for k in (
        "name", "description", "positioning", "voice", "tone", "audience", "location", "goals", "website", "colors",
        "visual_guidelines", "approved_claims", "restricted_claims", "prohibited_messaging", "constraints",
        "permitted_sources", "content_pillars", "languages", "marketing_objectives", "platform_preferences",
        "posting_constraints", "fonts") if k in brand})
    assert r.status_code == 200, r.text
    assert not any(p["is_active"] for p in api.get("/api/products").json())


def test_old_content_cannot_reuse_archived_products(poojaloka_seeded, monkeypatch):
    api = poojaloka_seeded
    item, p = _post_with_product(api)
    other = next(x for x in api.get("/api/products").json() if x["id"] != p["id"])
    _move_off_poojaloka_without_cleanup()

    seen: list = []
    real = content_routes.get_generator

    class Recording:
        def __init__(self, gen):
            self._gen = gen

        def __getattr__(self, name):
            attr = getattr(self._gen, name)
            if not callable(attr):
                return attr

            def call(*args, **kw):
                seen.append(args[-1] if args and isinstance(args[-1], list) else None)
                return attr(*args, **kw)
            return call

    monkeypatch.setattr(content_routes, "get_generator", lambda llm: Recording(real(llm)))
    assert api.post(f"/api/content/{item['id']}/regenerate", json={}).status_code == 200
    assert api.post(f"/api/content/{item['id']}/variants", json={"platforms": ["facebook"]}).status_code == 200
    assert seen and all(s == [] for s in seen if s is not None)  # no archived product facts reach the generator

    r = api.post(f"/api/content/{item['id']}/creative", json={}).json()
    meta = r["assets"][0]["meta"]
    assert meta["product_ids"] == [] and meta["photo_asset_id"] is None

    fresh = api.get(f"/api/content/{item['id']}").json()
    keep = api.put(f"/api/content/{item['id']}", json={"caption": "Updated copy", "product_ids": fresh["product_ids"]})
    assert keep.status_code == 200, keep.text  # existing references don't block editing…
    report = api.post(f"/api/content/{item['id']}/validate").json()
    checks = (report.get("validation") or report)["product_claims"]
    assert any(c["code"] == "listing" and c["status"] == "fail" for c in checks)  # …but are flagged
    added = api.put(f"/api/content/{item['id']}", json={"product_ids": [*fresh["product_ids"], other["id"]]})
    assert added.status_code == 400 and "another store" in added.text
