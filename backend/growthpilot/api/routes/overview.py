from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ... import usage
from ...adapters import available_adapters
from ...config import get_settings
from ...models import (
    AgentRun,
    ApprovalRequest,
    Brand,
    Campaign,
    ChannelConnection,
    ContentItem,
    ContentStatus,
    Experiment,
    Product,
    Recommendation,
    ResearchFinding,
    utcnow,
)
from ...services import analytics
from .. import serializers as S
from ..deps import Ctx, get_ctx

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview")
def overview(ctx: Ctx = Depends(get_ctx)):
    db, ws = ctx.db, ctx.workspace.id
    s = get_settings()
    counts = dict(db.execute(select(ContentItem.status, func.count()).where(ContentItem.workspace_id == ws)
                             .group_by(ContentItem.status)).all())
    active = db.execute(select(Campaign).where(Campaign.workspace_id == ws, Campaign.status.in_(["planned", "active"]))
                        .order_by(Campaign.created_at.desc()).limit(5)).scalars().all()
    upcoming = db.execute(select(ContentItem).where(ContentItem.workspace_id == ws,
                                                    ContentItem.status == ContentStatus.SCHEDULED)
                          .order_by(ContentItem.scheduled_at).limit(6)).scalars().all()
    failed = db.execute(select(ContentItem).where(ContentItem.workspace_id == ws, ContentItem.status == ContentStatus.FAILED)
                        .order_by(ContentItem.updated_at.desc()).limit(5)).scalars().all()
    runs = db.execute(select(AgentRun).where(AgentRun.workspace_id == ws).order_by(AgentRun.created_at.desc())
                      .limit(5)).scalars().all()
    recs = db.execute(select(Recommendation).where(Recommendation.workspace_id == ws, Recommendation.status == "open")
                      .order_by(Recommendation.created_at.desc()).limit(4)).scalars().all()
    gaps = db.execute(select(ResearchFinding).where(ResearchFinding.workspace_id == ws,
                                                    ResearchFinding.classification == "inference",
                                                    ResearchFinding.topic != "")
                      .order_by(ResearchFinding.created_at.desc()).limit(4)).scalars().all()
    allowed = available_adapters()
    conns = [c for c in db.execute(select(ChannelConnection).where(ChannelConnection.workspace_id == ws)).scalars()
             if c.adapter in allowed]
    has_brand = db.execute(select(func.count(Brand.id)).where(Brand.workspace_id == ws)).scalar_one() > 0
    n_products = db.execute(select(func.count(Product.id)).where(Product.workspace_id == ws)).scalar_one()
    exps = db.execute(select(Experiment).where(Experiment.workspace_id == ws).order_by(Experiment.created_at.desc())
                      .limit(3)).scalars().all()
    stats = analytics.summary(db, ws)
    pending_requests = db.execute(select(func.count(ApprovalRequest.id)).where(
        ApprovalRequest.workspace_id == ws, ApprovalRequest.status == "pending")).scalar_one()
    brand = db.execute(select(Brand).where(Brand.workspace_id == ws).order_by(Brand.id)).scalars().first()
    next_actions = []
    if not has_brand:
        next_actions.append({"label": "Set up your Brand Brain", "href": "/brand"})
    elif n_products == 0:
        next_actions.append({"label": "Add products to the catalogue", "href": "/brand#products"})
    if pending_requests:
        next_actions.append({"label": f"{pending_requests} budget or strategy request(s) need a decision",
                             "href": "/approvals"})
    if counts.get("in_review"):
        next_actions.append({"label": f"Review {counts['in_review']} post(s) waiting for approval", "href": "/approvals"})
    if not conns:
        next_actions.append({"label": "Connect a publishing channel", "href": "/integrations"})
    if any(r.status == "awaiting_approval" for r in runs):
        next_actions.append({"label": "An agent run is waiting on your approval", "href": "/agent"})
    if has_brand and not runs:
        next_actions.append({"label": "Give the agent its first goal", "href": "/agent"})
    if failed:
        next_actions.append({"label": f"{len(failed)} post(s) failed to publish", "href": "/calendar"})
    return {
        "mode": s.app_mode.value, "live_publishing_enabled": s.live_publishing_enabled,
        "counts": counts, "active_campaigns": [S.campaign(c) for c in active],
        "upcoming": [S.content(i, ctx.tz) for i in upcoming], "failed": [S.content(i, ctx.tz) for i in failed],
        "runs": [S.run(r) for r in runs], "recommendations": [S.recommendation(r) for r in recs],
        "opportunities": [S.finding(f) for f in gaps], "experiments": [S.experiment(e) for e in exps],
        "connections": [S.connection(c) for c in conns],
        "performance": {k: stats[k] for k in ("data_source", "freshness", "published", "with_metrics", "totals",
                                              "by_content_type", "by_platform")},
        "next_actions": next_actions, "has_brand": has_brand, "pending_requests": pending_requests,
        "usage": {"month_cost_usd": usage.spent(db, workspace_id=ws, since=usage.month_start(utcnow())), "monthly_budget_usd": ctx.workspace.monthly_budget_usd},
        "brand": {"name": brand.name, "is_synthetic": brand.is_synthetic, "colors": brand.colors,
                  "catalogue": (brand.catalogue_source or {}).get("label")} if brand else None,
    }
