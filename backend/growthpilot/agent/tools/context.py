from __future__ import annotations

from pydantic import Field
from sqlalchemy import func, select

from ...models import ChannelConnection, Competitor, Experiment, Recommendation
from ..generation import product_dict
from ..registry import Permission, ToolContext, ToolInput, ToolResult, tool
from .common import brand, brief, products


class LoadBrandIn(ToolInput):
    pass


@tool("load_brand_context", "Load the brand profile, personas, claims policy, connected channels and prior learnings.",
      LoadBrandIn, Permission.READ)
def load_brand_context(ctx: ToolContext, inp: LoadBrandIn) -> ToolResult:
    b = brand(ctx)
    data = brief(ctx)
    n_comp = ctx.db.execute(select(func.count(Competitor.id)).where(Competitor.brand_id == b.id)).scalar_one()
    conns = ctx.db.execute(select(ChannelConnection).where(ChannelConnection.workspace_id == ctx.workspace_id)
                           ).scalars().all()
    running = ctx.db.execute(select(func.count(Experiment.id)).where(
        Experiment.workspace_id == ctx.workspace_id, Experiment.status == "running")).scalar_one()
    open_recs = ctx.db.execute(select(func.count(Recommendation.id)).where(
        Recommendation.workspace_id == ctx.workspace_id, Recommendation.status == "open")).scalar_one()
    data.update({"competitors": n_comp, "permitted_sources": b.permitted_sources, "website": b.website,
                 "channels": [{"id": c.id, "adapter": c.adapter, "status": c.status, "label": c.account_label}
                              for c in conns], "running_experiments": running, "open_recommendations_count": open_recs,
                 "is_synthetic_brand": b.is_synthetic})
    ctx.remember("has_competitors", n_comp > 0)
    ctx.remember("running_experiments", running)
    summary = (f"Loaded {b.name}: {len(data['personas'])} personas, {len(b.approved_claims or [])} approved claims, "
               f"{n_comp} competitors, {len(conns)} channel(s), {running} running experiment(s).")
    if data["learnings"]:
        summary += f" Prior learning available: “{data['learnings'][0][:120]}…”"
    return ToolResult(summary, data, is_mock=b.is_synthetic)


class CatalogueIn(ToolInput):
    category: str | None = Field(default=None, description="Product category to filter, e.g. 'sofa'.")
    product_ids: list[int] = Field(default_factory=list)


@tool("retrieve_product_catalogue", "Fetch verified product facts (price, dimensions, materials, finishes, "
      "verified attributes). Only these facts may appear in content.", CatalogueIn, Permission.READ)
def retrieve_product_catalogue(ctx: ToolContext, inp: CatalogueIn) -> ToolResult:
    rows = products(ctx, inp.product_ids, inp.category)
    if not rows and inp.category:
        rows = products(ctx)
        note = f"No '{inp.category}' products; returned the full catalogue instead."
    else:
        note = ""
    ctx.remember("product_ids", [p.id for p in rows])
    synthetic = bool(rows) and all(p.is_synthetic for p in rows)
    summary = f"{len(rows)} product(s): " + ", ".join(p.name for p in rows[:6]) + (". " + note if note else ".")
    return ToolResult(summary, {"products": [product_dict(p) for p in rows]}, is_mock=synthetic)
