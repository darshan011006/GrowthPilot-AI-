from __future__ import annotations

from pydantic import Field

from ...models import Asset, ContentItem, ContentStatus
from ...services import assets as asset_service
from ...services.content import EDITABLE_FIELDS, normalise_hashtags, update
from ..generation import SlotContentOut, product_dict
from ..registry import Permission, ToolContext, ToolError, ToolInput, ToolResult, tool
from .common import brand, brief, generator, items, products

EDITABLE = {ContentStatus.DRAFT, ContentStatus.CHANGES_REQUESTED, ContentStatus.IN_REVIEW}


def _slot(item: ContentItem, idx: int, occasion: str | None) -> dict:
    return {"index": idx, "date": item.planned_at.isoformat() if item.planned_at else None, "pillar": item.pillar,
            "content_type": item.content_type, "variant": item.variant_label, "platform": item.platform,
            "occasion": occasion}


def _apply(ctx: ToolContext, item: ContentItem, fields: dict, note: str) -> None:
    update(ctx.db, item, {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}, user_id=None, role="editor",
           source=f"agent:{ctx.run.planner}", note=note)


class ContentIdsIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list, description="Empty = the content created in this run.")


@tool("generate_content_brief", "Write the creative brief for each slot: image brief, carousel outline (for "
      "carousels) and rationale, using only catalogue facts.", ContentIdsIn, Permission.DRAFT)
def generate_content_brief(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    gen = generator(ctx)
    b = brief(ctx)
    drafts = dict(ctx.state.get("drafts", {}))
    tokens, done = 0, []
    for idx, item in enumerate(items(ctx, inp.content_ids)):
        if item.status not in EDITABLE:
            continue
        prods = [product_dict(p) for p in products(ctx, item.product_ids)] if item.product_ids else []
        out, t = gen.slot_content(b, _slot(item, idx, b.get("occasion")), prods)
        tokens += t
        drafts[str(item.id)] = out.model_dump()
        _apply(ctx, item, {"image_brief": out.image_brief, "carousel_outline": out.carousel_outline,
                           "title": out.title[:255]}, "Creative brief")
        item.rationale = out.rationale[:2000]
        done.append(item.id)
    ctx.remember("drafts", drafts)
    return ToolResult(f"Briefs written for {len(done)} item(s).", {"content_ids": done, "generator": gen.name},
                      is_mock=gen.is_mock, tokens=tokens)


class CaptionIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list)
    revise: bool = Field(default=False, description="Revise to fix the latest validation failures.")


@tool("generate_caption", "Write (or revise after failed validation) the hook, caption, hashtags and CTA for each "
      "item. Revisions target the specific failed checks.", CaptionIn, Permission.DRAFT)
def generate_caption(ctx: ToolContext, inp: CaptionIn) -> ToolResult:
    gen = generator(ctx)
    b = brief(ctx)
    drafts = dict(ctx.state.get("drafts", {}))
    tokens, done, revised = 0, [], []
    for idx, item in enumerate(items(ctx, inp.content_ids)):
        if item.status not in EDITABLE:
            continue
        prods = [product_dict(p) for p in products(ctx, item.product_ids)] if item.product_ids else []
        if inp.revise:
            v = item.validation or {}
            failures = [c for section in ("product_claims", "brand") for c in v.get(section, [])
                        if c.get("status") == "fail"]
            if not failures:
                continue
            current = {"title": item.title, "hook": item.hook, "caption": item.caption, "hashtags": item.hashtags,
                       "cta": item.cta, "image_brief": item.image_brief, "carousel_outline": item.carousel_outline,
                       "product_ids": item.product_ids}
            out, t = gen.revise(b, current, failures, prods)
            note = "Revised after validation: " + "; ".join(f["message"] for f in failures)[:500]
            revised.append({"content_id": item.id, "fixed": [f["message"] for f in failures]})
        else:
            cached = drafts.get(str(item.id))
            if cached:
                out, t = SlotContentOut(**cached), 0
            else:
                out, t = gen.slot_content(b, _slot(item, idx, b.get("occasion")), prods)
            note = "Caption drafted"
        tokens += t
        _apply(ctx, item, {"hook": out.hook[:500], "caption": out.caption, "hashtags": normalise_hashtags(out.hashtags),
                           "cta": out.cta[:255],
                           "product_ids": [i for i in out.product_ids if i in {p["id"] for p in prods}] or item.product_ids},
               note)
        item.rationale = out.rationale[:2000]
        done.append(item.id)
    msg = (f"Revised {len(revised)} item(s) to fix validation failures." if inp.revise
           else f"Captions drafted for {len(done)} item(s).")
    return ToolResult(msg, {"content_ids": done, "revisions": revised, "generator": gen.name}, is_mock=gen.is_mock,
                      tokens=tokens)


@tool("generate_image_asset", "Attach images: the product's real photo if one exists; otherwise a clearly labelled "
      "placeholder rendered from the image brief (no image-generation provider is implemented).", ContentIdsIn,
      Permission.DRAFT, implementation="real product photos when uploaded; labelled placeholder otherwise")
def generate_image_asset(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    b = brand(ctx)
    real, placeholders, done = 0, 0, []
    for item in items(ctx, inp.content_ids):
        if item.status not in EDITABLE or item.asset_id:
            continue
        prods = products(ctx, item.product_ids) if item.product_ids else []
        photo = next((ctx.db.get(Asset, p.image_asset_id) for p in prods if p.image_asset_id), None)
        if photo is not None:
            cover, real = photo, real + 1
        else:
            cover = asset_service.make_placeholder(ctx.db, workspace_id=ctx.workspace_id, brand_id=b.id,
                                                   title=item.title or item.pillar, brief=item.image_brief,
                                                   colors=b.colors, synthetic=ctx.settings.is_demo)
            placeholders += 1
        slides = []
        if item.content_type == "carousel":
            for line in (item.carousel_outline or ["Slide 2"])[1:5]:
                s = asset_service.make_placeholder(ctx.db, workspace_id=ctx.workspace_id, brand_id=b.id,
                                                   title=line[:40], brief=line, colors=b.colors,
                                                   synthetic=ctx.settings.is_demo)
                slides.append(s.id)
                placeholders += 1
        _apply(ctx, item, {"asset_id": cover.id, "slide_asset_ids": slides}, "Images attached")
        done.append(item.id)
    if not done:
        raise ToolError("No items needed images.")
    return ToolResult(f"Images attached to {len(done)} item(s): {real} real product photo(s), {placeholders} labelled "
                      "placeholder(s). Placeholders must be replaced before live publishing.",
                      {"content_ids": done, "real_photos": real, "placeholders": placeholders},
                      is_mock=placeholders > 0)
