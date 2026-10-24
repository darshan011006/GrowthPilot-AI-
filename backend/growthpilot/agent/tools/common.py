from __future__ import annotations

from sqlalchemy import select

from ...llm import get_llm
from ...models import Brand, ContentItem, Experiment, Persona, Product, Recommendation
from ..generation import Generator, get_generator
from ..registry import ToolBlocked, ToolContext, ToolError


def brand(ctx: ToolContext) -> Brand:
    if not ctx.brand_id:
        raise ToolBlocked("No brand is set up for this workspace. Create one in Brand Brain first.",
                          blocker="brand_missing")
    b = ctx.db.get(Brand, ctx.brand_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise ToolBlocked("Brand not found.", blocker="brand_missing")
    return b


def generator(ctx: ToolContext) -> Generator:
    return get_generator(get_llm())


def items(ctx: ToolContext, ids: list[int]) -> list[ContentItem]:
    if not ids:
        ids = list(ctx.state.get("content_ids", []))
    rows = ctx.db.execute(select(ContentItem).where(ContentItem.id.in_(ids),
                                                    ContentItem.workspace_id == ctx.workspace_id)).scalars().all()
    if not rows:
        raise ToolError("No matching content items in this workspace.")
    return sorted(rows, key=lambda i: (i.planned_at or i.created_at, i.id))


def brief(ctx: ToolContext) -> dict:
    b = brand(ctx)
    params = ctx.state.get("params", {})
    learnings = [e.learnings for e in ctx.db.execute(
        select(Experiment).where(Experiment.workspace_id == ctx.workspace_id, Experiment.status == "evaluated")
        .order_by(Experiment.evaluated_at.desc()).limit(3)).scalars() if e.learnings]
    recs = [r.title for r in ctx.db.execute(select(Recommendation).where(
        Recommendation.workspace_id == ctx.workspace_id, Recommendation.status == "open").limit(5)).scalars()]
    personas = ctx.db.execute(select(Persona).where(Persona.brand_id == b.id)).scalars().all()
    return {
        "brand": {k: getattr(b, k) for k in ("name", "description", "positioning", "voice", "tone", "audience",
                                             "location", "goals", "visual_guidelines", "approved_claims",
                                             "restricted_claims", "prohibited_messaging", "constraints")},
        "personas": [{"name": p.name, "description": p.description, "goals": p.goals, "pain_points": p.pain_points}
                     for p in personas],
        "focus_category": params.get("category"), "geography": params.get("geography") or b.location,
        "occasion": params.get("occasion"), "learnings": learnings, "open_recommendations": recs,
    }


def products(ctx: ToolContext, ids: list[int] | None = None, category: str | None = None) -> list[Product]:
    q = select(Product).where(Product.workspace_id == ctx.workspace_id, Product.brand_id == ctx.brand_id,
                              Product.is_active.is_(True))
    if ids:
        q = q.where(Product.id.in_(ids))
    elif category:
        q = q.where(Product.category.ilike(f"%{category}%"))
    return list(ctx.db.execute(q.order_by(Product.id)).scalars())
