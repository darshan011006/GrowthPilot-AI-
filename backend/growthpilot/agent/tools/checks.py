from __future__ import annotations

from ...services.validation import validate_item
from ..registry import Permission, ToolContext, ToolResult, tool
from .common import items
from .creative import ContentIdsIn


def _run(ctx: ToolContext, inp: ContentIdsIn, section: str, label: str) -> ToolResult:
    rows, failing, warnings = [], {}, 0
    for item in items(ctx, inp.content_ids):
        if item.status in ("published", "publishing", "cancelled"):
            continue
        report = validate_item(ctx.db, item)
        checks = getattr(report, section)
        fails = [c for c in checks if c.status == "fail"]
        warns = [c for c in checks if c.status == "warn"]
        warnings += len(warns)
        rows.append({"content_id": item.id, "version": item.version, "fail": [c.message for c in fails],
                     "warn": [c.message for c in warns], "pass": sum(1 for c in checks if c.status == "pass")})
        if fails:
            failing[item.id] = [{"code": c.code, "message": c.message, "claim": c.claim} for c in fails]
    state = dict(ctx.state.get("validation_failures", {}))
    for row in rows:
        key = f"{section}:{row['content_id']}"
        if row["content_id"] in failing:
            state[key] = failing[row["content_id"]]
        else:
            state.pop(key, None)
    ctx.remember("validation_failures", state)
    summary = (f"{label}: {len(rows) - len(failing)}/{len(rows)} item(s) pass"
               + (f"; {len(failing)} fail" if failing else "") + (f"; {warnings} warning(s)" if warnings else "") + ".")
    return ToolResult(summary, {"results": rows, "failing_ids": sorted(failing)})


@tool("validate_product_claims", "Check every price, discount, warranty, material, dimension, stock/delivery and "
      "certification claim against the catalogue and approved-claims list.", ContentIdsIn, Permission.READ)
def validate_product_claims(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    return _run(ctx, inp, "product_claims", "Product claims")


@tool("validate_brand_consistency", "Check tone, prohibited messaging, competitor mentions, originality versus "
      "observed competitor content, CTAs and placeholders.", ContentIdsIn, Permission.READ)
def validate_brand_consistency(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    return _run(ctx, inp, "brand", "Brand consistency")


@tool("validate_platform_constraints", "Check platform rules (Instagram: caption ≤2200 chars, ≤30 hashtags, JPEG "
      "media, 4:5–1.91:1 aspect ratio, carousel 2–10 images, supported formats).", ContentIdsIn, Permission.READ)
def validate_platform_constraints(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    return _run(ctx, inp, "platform", "Platform constraints")
