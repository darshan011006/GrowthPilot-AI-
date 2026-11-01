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


@router.get("/instagram-account")
def instagram_account(refresh: bool = False, ctx: Ctx = Depends(get_ctx)):
    if refresh:
        rate_limit(f"ig-account:{ctx.workspace.id}", 12, 3600)
    return analytics.instagram_account(ctx.db, ctx.workspace.id, force=refresh)


@router.post("/collect")
def collect(ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    rate_limit(f"collect:{ctx.workspace.id}", 30, 3600)
    stats = analytics.collect(ctx.db, ctx.workspace.id, force=True)
    return stats
