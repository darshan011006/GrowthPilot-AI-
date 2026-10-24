"""Creative Agent tools: briefs, captions (and targeted revisions), rendered image files."""

from __future__ import annotations

from pydantic import Field

from ...models import ContentItem, ContentStatus
from ...services import creative as creative_service
from ...services.content import EDITABLE_FIELDS, normalise_hashtags, update
from ...services.errors import WorkflowError
from ..generation import SlotContentOut, product_dict
from ..registry import Effect, Permission, Role, ToolContext, ToolError, ToolInput, ToolResult, tool
from .common import brief, generator, items, products

C = Role.CREATIVE
EDITABLE = {ContentStatus.DRAFT, ContentStatus.CHANGES_REQUESTED, ContentStatus.IN_REVIEW}


def _slot(ctx: ToolContext, item: ContentItem, idx: int, pillar_index: int = 0) -> dict:
    occasion = ctx.state.get("params", {}).get("occasion")
    arts = ctx.state.get("articles") or []
    return {"index": idx, "date": item.planned_at.isoformat() if item.planned_at else None, "pillar": item.pillar,
            "content_type": item.content_type, "variant": item.variant_label, "platform": item.platform,
            "occasion": occasion, "festival": ctx.state.get("festival"), "pillar_index": pillar_index,
            "article": arts[pillar_index % len(arts)] if arts else None}


def _pillar_counts(rows: list[ContentItem]) -> dict[int, int]:
    """How many earlier items in the list share each item's pillar (so repeats take a different angle)."""
    seen: dict[str, int] = {}
    out = {}
    for it in rows:
        out[it.id] = seen.get(it.pillar, 0)
        seen[it.pillar] = out[it.id] + 1
    return out


def apply(ctx: ToolContext, item: ContentItem, fields: dict, note: str) -> None:
    update(ctx.db, item, {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}, user_id=None, role="editor",
           source=f"agent:{ctx.run.planner}", note=note)


class ContentIdsIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list, description="Empty = the posts created in this run.")


@tool("create_content_brief", "Write the creative brief for each calendar slot: image brief, carousel outline (for "
      "carousels) and rationale, using only catalogue facts and the brand's own published content.", ContentIdsIn,
      Permission.DRAFT, role=C, effects=(Effect.LOCAL_WRITE, Effect.COST))
def create_content_brief(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    gen = generator(ctx)
    b = brief(ctx)
    drafts = dict(ctx.state.get("drafts", {}))
    tokens, done = 0, []
    rows = items(ctx, inp.content_ids)
    counts = _pillar_counts(rows)
    for idx, item in enumerate(rows):
        if item.status not in EDITABLE:
            continue
        prods = [product_dict(p) for p in products(ctx, item.product_ids)] if item.product_ids else []
        out, t = gen.slot_content(b, _slot(ctx, item, idx, counts[item.id]), prods)
        tokens += t
        drafts[str(item.id)] = out.model_dump()
        apply(ctx, item, {"image_brief": out.image_brief, "carousel_outline": out.carousel_outline,
                          "title": out.title[:255]}, "Creative brief")
        item.rationale = out.rationale[:2000]
        done.append(item.id)
    ctx.remember("drafts", drafts)
    return ToolResult(f"Briefs written for {len(done)} item(s).", {"content_ids": done, "generator": gen.name},
                      is_mock=gen.is_mock, tokens=tokens)


class CaptionIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list)
    revise: bool = Field(default=False, description="Revise to fix the latest verification failures.")


@tool("generate_caption", "Write (or revise after failed verification) the hook, caption, hashtags and CTA for each "
      "item. Revisions target the specific failed checks and change as little as possible.", CaptionIn,
      Permission.DRAFT, role=C, effects=(Effect.LOCAL_WRITE, Effect.COST))
def generate_caption(ctx: ToolContext, inp: CaptionIn) -> ToolResult:
    gen = generator(ctx)
    b = brief(ctx)
    drafts = dict(ctx.state.get("drafts", {}))
    fails_state = ctx.state.get("validation_failures", {})
    tokens, done, revised = 0, [], []
    rows = items(ctx, inp.content_ids)
    counts = _pillar_counts(rows)
    for idx, item in enumerate(rows):
        if item.status not in EDITABLE:
            continue
        prods = [product_dict(p) for p in products(ctx, item.product_ids)] if item.product_ids else []
        if inp.revise:
            v = item.validation or {}
            failures = [c for section in ("product_claims", "brand") for c in v.get(section, [])
                        if c.get("status") == "fail"]
            failures += [{"message": f["message"], "claim": f.get("claim", ""), "code": f.get("code", "")}
                         for k in (f"product_claims:{item.id}", f"brand:{item.id}") for f in fails_state.get(k, [])
                         if f.get("message") not in {x.get("message") for x in failures}]
            if not failures:
                continue
            current = {"title": item.title, "hook": item.hook, "caption": item.caption, "hashtags": item.hashtags,
                       "cta": item.cta, "image_brief": item.image_brief, "carousel_outline": item.carousel_outline,
                       "product_ids": item.product_ids}
            out, t = gen.revise(b, current, failures, prods)
            note = "Revised after verification: " + "; ".join(f["message"] for f in failures)[:500]
            revised.append({"content_id": item.id, "fixed": [f["message"] for f in failures]})
        else:
            cached = drafts.get(str(item.id))
            if cached:
                out, t = SlotContentOut(**cached), 0
            else:
                out, t = gen.slot_content(b, _slot(ctx, item, idx, counts[item.id]), prods)
            note = "Caption drafted"
        tokens += t
        apply(ctx, item, {"hook": out.hook[:500], "caption": out.caption, "hashtags": normalise_hashtags(out.hashtags),
                          "cta": out.cta[:255],
                          "product_ids": [i for i in out.product_ids if i in {p["id"] for p in prods}] or item.product_ids},
              note)
        item.rationale = out.rationale[:2000]
        done.append(item.id)
    msg = (f"Revised {len(revised)} item(s) to fix verification failures." if inp.revise
           else f"Captions drafted for {len(done)} item(s).")
    return ToolResult(msg, {"content_ids": done, "revisions": revised, "generator": gen.name}, is_mock=gen.is_mock,
                      tokens=tokens)


class CreativeIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list)
    rerender: bool = Field(default=False, description="Render again even if an image is attached.")
    variation: int = Field(default=0, ge=0, le=5, description="Layout/colour variation.")
    ai_background: bool = Field(default=False, description="Use the configured image provider for the background "
                                                           "(costs money; product imagery stays real).")


def render_item(ctx: ToolContext, item: ContentItem, *, variation: int = 0, ai_background: bool = False) -> list[int]:
    """Render the cover (and carousel slides) for one item and attach them. Returns new asset ids."""
    cover = creative_service.render_for_item(ctx.db, item, variation=variation, ai_background=ai_background)
    slides = []
    if item.content_type == "carousel":
        from ...platforms import SPECS

        sp = SPECS.get(item.platform)
        limit = (sp.carousel_max if sp and sp.carousel_max else 10) - 1
        outline = [x for x in (item.carousel_outline or [])[1:] if x.strip()][:max(1, min(limit, 5))]
        if not outline:
            outline = [item.cta or item.title]
        total = len(outline) + 1
        for i, line in enumerate(outline, start=2):
            a = creative_service.render_for_item(ctx.db, item, slide=(i, total), headline=line, variation=variation)
            slides.append(a.id)
    apply(ctx, item, {"asset_id": cover.id, "slide_asset_ids": slides}, f"Rendered {cover.meta.get('template')} "
          f"image{'s' if slides else ''} ({cover.width}×{cover.height})")
    return [cover.id, *slides]


@tool("generate_creative_asset", "Render real, downloadable JPEG posters (and carousel slides) for each item in the "
      "platform's format: brand colours and fonts, verified catalogue facts, the store's real product photo when one "
      "exists — otherwise a typographic product card (stock images are never shown as the product). On-image text is "
      "claim-checked. Optional AI background via the image provider.", CreativeIn, Permission.DRAFT,
      implementation="local Pillow renderer (free); optional Gemini image background", role=C,
      effects=(Effect.LOCAL_WRITE,))
def generate_creative_asset(ctx: ToolContext, inp: CreativeIn) -> ToolResult:
    done, failed, new_assets = [], [], []
    fails = dict(ctx.state.get("validation_failures", {}))
    for item in items(ctx, inp.content_ids):
        if item.status not in EDITABLE or (item.asset_id and not inp.rerender):
            continue
        if item.content_type in ("video", "reel", "story"):
            continue
        try:
            ids = render_item(ctx, item, variation=inp.variation, ai_background=inp.ai_background)
            new_assets += ids
            done.append(item.id)
            fails.pop(f"creative:{item.id}", None)
            key = f"product_claims:{item.id}"
            if key in fails:
                fails[key] = [f for f in fails[key] if f.get("code") != "on_image_text"]
                if not fails[key]:
                    fails.pop(key)
        except WorkflowError as exc:
            failed.append({"content_id": item.id, "reason": str(exc)})
            fails[f"product_claims:{item.id}"] = [f for f in fails.get(f"product_claims:{item.id}", [])
                                                  if f.get("code") != "on_image_text"] + [
                {"code": "on_image_text", "message": str(exc), "claim": item.hook}]
    ctx.remember("validation_failures", fails)
    ctx.remember_ids("asset_ids", new_assets)
    if not done and not failed:
        raise ToolError("No items needed images.")
    return ToolResult(f"Rendered {len(new_assets)} image file(s) for {len(done)} item(s)"
                      + (f"; {len(failed)} item(s) held: on-image text failed checks" if failed else "") + ".",
                      {"content_ids": done, "asset_ids": new_assets, "failed": failed})
