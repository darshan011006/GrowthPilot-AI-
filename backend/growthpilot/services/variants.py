"""Platform variants: one main post adapted to another platform as its own item (own version, approval and status)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ContentItem
from ..platforms import SPECS
from .content import add_revision, normalise_hashtags

PLATFORM_OFFSET = {"instagram": 0, "facebook": 90, "pinterest": 150, "threads": 210, "x": 240, "linkedin": 60,
                   "youtube": 300}  # minutes after the main post


def variant_type(master: ContentItem, platform: str) -> str:
    sp = SPECS[platform]
    if master.content_type in sp.content_types:
        return master.content_type
    if "post" in sp.content_types:
        return "post"
    return "video" if "video" in sp.content_types else "text"


def existing_variant(db: Session, master: ContentItem, platform: str) -> ContentItem | None:
    return db.execute(select(ContentItem).where(ContentItem.master_id == master.id,
                                                ContentItem.platform == platform)).scalars().first()


def platform_info(platform: str) -> dict:
    sp = SPECS[platform]
    return {"key": platform, "label": sp.label, "tone": sp.tone, "caption_max": sp.caption_max,
            "hashtags_max": sp.hashtags_max, "content_types": list(sp.content_types)}


def adapted_fields(gen, brief: dict, master: ContentItem, platform: str, products: list[dict]) -> tuple[dict, int, str]:
    out, tokens = gen.adapt(brief, {"title": master.title, "hook": master.hook, "caption": master.caption,
                                    "hashtags": master.hashtags, "cta": master.cta,
                                    "content_type": master.content_type}, platform_info(platform), products)
    ctype = variant_type(master, platform)
    fields = {"title": out.title[:255], "hook": out.hook[:500], "caption": out.caption,
              "hashtags": normalise_hashtags(out.hashtags), "cta": out.cta[:255],
              "video_script": out.caption if ctype == "video" else ""}
    return fields, tokens, out.rationale


def create_variant(db: Session, master: ContentItem, platform: str, gen, brief: dict, products: list[dict], *,
                   run_id: str | None = None, created_by: int | None = None) -> tuple[ContentItem, int]:
    fields, tokens, rationale = adapted_fields(gen, brief, master, platform, products)
    v = ContentItem(workspace_id=master.workspace_id, brand_id=master.brand_id, campaign_id=master.campaign_id,
                    experiment_id=master.experiment_id, variant_label=master.variant_label, run_id=run_id,
                    platform=platform, master_id=master.id, content_type=variant_type(master, platform),
                    pillar=master.pillar, image_brief=master.image_brief,
                    carousel_outline=list(master.carousel_outline or []), product_ids=list(master.product_ids or []),
                    planned_at=(master.planned_at + timedelta(minutes=PLATFORM_OFFSET.get(platform, 120)))
                    if master.planned_at else None, generated_by=gen.name, rationale=rationale[:2000],
                    created_by=created_by, is_synthetic=master.is_synthetic, **fields)
    db.add(v)
    db.flush()
    add_revision(db, v, gen.name, created_by, f"Variant of #{master.id} for {SPECS[platform].label}")
    return v, tokens
