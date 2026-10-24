from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from ... import audit
from ...models import Competitor, ResearchFinding
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx
from .brand import current_brand

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/research/findings")
def findings(classification: str = "", source_type: str = "", run_id: str = "", q: str = "",
             ctx: Ctx = Depends(get_ctx)):
    query = select(ResearchFinding).where(ResearchFinding.workspace_id == ctx.workspace.id)
    if classification:
        query = query.where(ResearchFinding.classification == classification)
    if source_type:
        query = query.where(ResearchFinding.source_type == source_type)
    if run_id:
        query = query.where(ResearchFinding.run_id == run_id)
    if q:
        query = query.where(ResearchFinding.statement.ilike(f"%{q[:100]}%"))
    rows = ctx.db.execute(query.order_by(ResearchFinding.retrieved_at.desc()).limit(300)).scalars().all()
    return [S.finding(f) for f in rows]


class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    website: str = Field(default="", max_length=255)
    instagram_url: str = Field(default="", max_length=255)
    notes: str = Field(default="", max_length=2000)


def _check(body: CompetitorIn) -> None:
    for url in (body.website, body.instagram_url):
        if url and not url.startswith("https://"):
            raise ApiError(400, "Competitor URLs must start with https://", "validation")


@router.get("/competitors")
def list_competitors(ctx: Ctx = Depends(get_ctx)):
    b = current_brand(ctx, required=False)
    if b is None:
        return []
    rows = ctx.db.execute(select(Competitor).where(Competitor.brand_id == b.id).order_by(Competitor.name)).scalars().all()
    return [S.competitor(c, with_obs=True) for c in rows]


@router.post("/competitors")
def add_competitor(body: CompetitorIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    _check(body)
    b = current_brand(ctx)
    c = Competitor(workspace_id=ctx.workspace.id, brand_id=b.id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    audit.record(ctx.db, "competitor.created", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="competitor", target_id=c.id, ip=ctx.ip)
    ctx.db.commit()
    return S.competitor(c)


@router.put("/competitors/{cid}")
def edit_competitor(cid: int, body: CompetitorIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    _check(body)
    c = ctx.get(Competitor, cid)
    for k, v in body.model_dump().items():
        setattr(c, k, v.strip())
    ctx.db.commit()
    return S.competitor(c)


@router.delete("/competitors/{cid}")
def delete_competitor(cid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    c = ctx.get(Competitor, cid)
    audit.record(ctx.db, "competitor.deleted", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="competitor", target_id=c.id, ip=ctx.ip)
    ctx.db.delete(c)
    ctx.db.commit()
    return {"ok": True}
