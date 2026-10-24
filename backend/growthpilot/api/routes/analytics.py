from __future__ import annotations

from fastapi import APIRouter, Depends

from ...services import analytics
from ..deps import Ctx, get_ctx, rate_limit

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def get_analytics(campaign_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    if campaign_id:
        from ...models import Campaign

        ctx.get(Campaign, campaign_id)
    return analytics.summary(ctx.db, ctx.workspace.id, campaign_id)


@router.post("/collect")
def collect(ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    rate_limit(f"collect:{ctx.workspace.id}", 30, 3600)
    stats = analytics.collect(ctx.db, ctx.workspace.id, force=True)
    return stats
