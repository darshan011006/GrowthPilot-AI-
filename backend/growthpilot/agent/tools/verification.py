"""Brand & Product Verification Agent tools. Deterministic checks the model can't override."""

from __future__ import annotations

import hashlib

from pydantic import Field

from ... import catalogue as catalogue_mod
from ...models import Product
from ...services.assets import store
from ...services.creative import creative_ok
from ...services.validation import item_assets, validate_item
from ..registry import Effect, Permission, Role, ToolContext, ToolInput, ToolResult, tool
from .common import brand, items, promotable

V = Role.VERIFICATION


class VerifyIn(ToolInput):
    scope: str = Field(default="content", pattern="^(catalogue|content)$",
                       description="catalogue = check product data before planning; content = check every claim.")
    content_ids: list[int] = Field(default_factory=list)
    product_ids: list[int] = Field(default_factory=list)
    variants: bool = Field(default=False, description="Check this run's platform variants instead of the main posts.")


def _record(ctx: ToolContext, section: str, rows: list[dict], failing: dict) -> None:
    state = dict(ctx.state.get("validation_failures", {}))
    for row in rows:
        key = f"{section}:{row['content_id']}"
        if row["content_id"] in failing:
            state[key] = failing[row["content_id"]]
        else:
            state.pop(key, None)
    ctx.remember("validation_failures", state)


@tool("verify_product_facts", "scope=catalogue: re-check the selected products at the source when a live connector "
      "is available (price, MRP, stock, listing), report freshness and data-quality problems, and exclude products "
      "that can't be promoted. scope=content: check every price, offer, warranty, material, size, stock/delivery, "
      "certification and health claim against the catalogue and the approved-claims list.", VerifyIn,
      Permission.READ, role=V, effects=(Effect.READ_ONLY, Effect.EXTERNAL_READ))
def verify_product_facts(ctx: ToolContext, inp: VerifyIn) -> ToolResult:
    if inp.scope == "catalogue":
        return _verify_catalogue(ctx, inp)
    key = "variant_ids" if inp.variants else "content_ids"
    rows, failing, warnings = [], {}, 0
    for item in items(ctx, inp.content_ids, key=key):
        if item.status in ("published", "publishing", "cancelled"):
            continue
        report = validate_item(ctx.db, item)
        fails = [c for c in report.product_claims if c.status == "fail"]
        warns = [c for c in report.product_claims if c.status == "warn"]
        warnings += len(warns)
        rows.append({"content_id": item.id, "platform": item.platform, "version": item.version,
                     "fail": [c.message for c in fails], "warn": [c.message for c in warns],
                     "pass": sum(1 for c in report.product_claims if c.status == "pass")})
        if fails:
            failing[item.id] = [{"code": c.code, "message": c.message, "claim": c.claim} for c in fails]
    # Keep on-image text failures recorded by the renderer until the item is re-rendered.
    state = ctx.state.get("validation_failures", {})
    for row in rows:
        extra = [f for f in state.get(f"product_claims:{row['content_id']}", []) if f.get("code") == "on_image_text"]
        if extra and row["content_id"] not in failing:
            failing[row["content_id"]] = extra
    _record(ctx, "product_claims", rows, failing)
    return ToolResult(f"Product claims: {len(rows) - len(failing)}/{len(rows)} item(s) pass"
                      + (f"; {len(failing)} fail" if failing else "") + (f"; {warnings} warning(s)" if warnings else "")
                      + ".", {"results": rows, "failing_ids": sorted(failing)})


def _verify_catalogue(ctx: ToolContext, inp: VerifyIn) -> ToolResult:
    b = brand(ctx)
    ids = inp.product_ids or ctx.state.get("product_ids", [])
    prods = [p for p in (ctx.db.get(Product, i) for i in ids) if p is not None and p.brand_id == b.id]
    source = catalogue_mod.get_source(b)
    refreshed = catalogue_mod.refresh(ctx.db, b, prods, source)
    usable, excluded, rows = [], [], []
    for p in prods:
        ok, why = promotable(p)
        fr = catalogue_mod.freshness(p)
        if ok and fr["state"] == "stale" and ctx.settings.is_live:
            ok, why = False, "facts are stale and couldn't be refreshed"
        if ok:
            usable.append(p)
        else:
            excluded.append({"id": p.id, "name": p.name, "reason": why})
        rows.append({"id": p.id, "sku": p.sku, "name": p.name, "promotable": ok, "reason": why,
                     "freshness": fr, "image_kind": p.image_kind,
                     "data_quality": [q.get("code") for q in p.data_quality or []]})
    usable_products = usable
    ctx.remember("product_ids", [p.id for p in usable_products])
    no_photos = sum(1 for p in usable_products if p.image_kind != "product_photo" and not p.image_asset_id)
    mode = ("refreshed at the source" if source else "not refreshed (bundled snapshot or manual data)")
    return ToolResult(
        f"Checked {len(prods)} product(s), {mode}: {len(usable_products)} usable, {len(excluded)} excluded"
        + (f", {len(refreshed['changed'])} change(s) found" if refreshed["changed"] else "")
        + f". {no_photos} usable product(s) have no real photo.",
        {"products": rows, "usable": [p.id for p in usable_products], "excluded": excluded, "no_photos": no_photos,
         "refresh": refreshed, "live_source": bool(source)}, is_mock=b.is_synthetic or not source)


class CreativeCheckIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list)
    variants: bool = False


@tool("validate_creative", "Check brand rules (tone, prohibited wording, competitor mentions, originality, "
      "placeholders), the platform's format rules (length, hashtags, media count, file type, aspect ratio, size) and "
      "the rendered images (contrast, safe margins, text fit, glyphs, dimensions, file integrity).", CreativeCheckIn,
      Permission.READ, role=V, effects=(Effect.READ_ONLY,))
def validate_creative(ctx: ToolContext, inp: CreativeCheckIn) -> ToolResult:
    key = "variant_ids" if inp.variants else "content_ids"
    rows, warnings = [], 0
    failing: dict[str, dict] = {"brand": {}, "platform": {}, "creative": {}}
    for item in items(ctx, inp.content_ids, key=key):
        if item.status in ("published", "publishing", "cancelled"):
            continue
        report = validate_item(ctx.db, item)
        row = {"content_id": item.id, "platform": item.platform, "fail": [], "warn": []}
        for section in ("brand", "platform"):
            checks = getattr(report, section)
            fails = [c for c in checks if c.status == "fail"]
            row["fail"] += [c.message for c in fails]
            row["warn"] += [c.message for c in checks if c.status == "warn"]
            if fails:
                failing[section][item.id] = [{"code": c.code, "message": c.message, "claim": c.claim} for c in fails]
        cfails = []
        for a in item_assets(ctx.db, item):
            if a.source != "rendered":
                continue
            ok, checks = creative_ok(a)
            cfails += [{"code": c.get("code"), "message": f"{a.filename}: {c.get('message')}", "claim": ""}
                       for c in checks if c.get("status") == "fail"]
            row["warn"] += [c.get("message") for c in checks if c.get("status") == "warn"]
            try:
                if hashlib.sha256(store().path(a.storage_key).read_bytes()).hexdigest() != a.sha256:
                    cfails.append({"code": "integrity", "message": f"{a.filename} changed on disk after rendering.",
                                   "claim": ""})
            except OSError:
                cfails.append({"code": "integrity", "message": f"{a.filename} is missing.", "claim": ""})
        if cfails:
            failing["creative"][item.id] = cfails
            row["fail"] += [c["message"] for c in cfails]
        warnings += len(row["warn"])
        rows.append(row)
    for section, f in failing.items():
        _record(ctx, section, rows, f)
    n_fail = len({cid for f in failing.values() for cid in f})
    return ToolResult(f"Brand, platform and image checks: {len(rows) - n_fail}/{len(rows)} item(s) pass"
                      + (f"; {n_fail} fail" if n_fail else "") + (f"; {warnings} warning(s)" if warnings else "") + ".",
                      {"results": rows, "failing_ids": sorted({cid for f in failing.values() for cid in f})})

