from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ... import audit
from ...models import Campaign, ContentItem, Experiment, Hypothesis, Recommendation, Report, ResearchFinding
from ...services import experiments as exp_service
from ...services import reports
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx
from .brand import current_brand

router = APIRouter(prefix="/api", tags=["campaigns"])


@router.get("/campaigns")
def list_campaigns(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(Campaign).where(Campaign.workspace_id == ctx.workspace.id)
                          .order_by(Campaign.created_at.desc())).scalars().all()
    counts = {}
    for cid, status, n in ctx.db.execute(select(ContentItem.campaign_id, ContentItem.status, func.count())
                                         .where(ContentItem.workspace_id == ctx.workspace.id)
                                         .group_by(ContentItem.campaign_id, ContentItem.status)).all():
        counts.setdefault(cid, {})[status] = n
    return [S.campaign(c, counts.get(c.id, {})) for c in rows]


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    objective: str = Field(default="", max_length=3000)
    audience: str = Field(default="", max_length=3000)
    geography: str = Field(default="", max_length=160)
    language: str = Field(default="English", max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    platforms: list[str] = Field(default_factory=lambda: ["instagram"])
    pillars: list[str] = Field(default_factory=list)
    creative_direction: str = Field(default="", max_length=3000)
    ctas: list[str] = Field(default_factory=list)
    budget_note: str = Field(default="", max_length=2000)
    measurement_plan: str = Field(default="", max_length=3000)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    status: str = "draft"


def _apply(c: Campaign, body: CampaignIn) -> None:
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise ApiError(400, "End date must be after the start date.", "validation")
    if body.status not in ("draft", "planned", "active", "completed", "archived"):
        raise ApiError(400, "Unknown status.", "validation")
    for k, v in body.model_dump().items():
        setattr(c, k, v)


@router.post("/campaigns")
def create_campaign(body: CampaignIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    b = current_brand(ctx)
    c = Campaign(workspace_id=ctx.workspace.id, brand_id=b.id, created_by=ctx.user.id)
    _apply(c, body)
    ctx.db.add(c)
    ctx.db.flush()
    audit.record(ctx.db, "campaign.created", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="campaign", target_id=c.id, ip=ctx.ip)
    ctx.db.commit()
    return S.campaign(c)


@router.put("/campaigns/{cid}")
def edit_campaign(cid: int, body: CampaignIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    c = ctx.get(Campaign, cid)
    _apply(c, body)
    audit.record(ctx.db, "campaign.updated", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="campaign", target_id=c.id, ip=ctx.ip)
    ctx.db.commit()
    return S.campaign(c)


@router.get("/campaigns/{cid}")
def get_campaign(cid: int, ctx: Ctx = Depends(get_ctx)):
    c = ctx.get(Campaign, cid)
    items = ctx.db.execute(select(ContentItem).where(ContentItem.campaign_id == c.id)
                           .order_by(ContentItem.planned_at)).scalars().all()
    hyps = ctx.db.execute(select(Hypothesis).where(Hypothesis.campaign_id == c.id).order_by(Hypothesis.rank)).scalars().all()
    ev_ids = sorted({i for h in hyps for i in (h.evidence_ids or [])})
    evidence = ctx.db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(ev_ids or [0]))).scalars().all()
    exps = ctx.db.execute(select(Experiment).where(Experiment.campaign_id == c.id)).scalars().all()
    recs = ctx.db.execute(select(Recommendation).where(Recommendation.campaign_id == c.id)).scalars().all()
    reps = ctx.db.execute(select(Report).where(Report.campaign_id == c.id).order_by(Report.created_at.desc())).scalars().all()
    return {"campaign": S.campaign(c), "items": [S.content(i, ctx.tz) for i in items],
            "hypotheses": [S.hypothesis(h) for h in hyps], "evidence": [S.finding(f) for f in evidence],
            "experiments": [S.experiment(e) for e in exps], "recommendations": [S.recommendation(r) for r in recs],
            "reports": [S.report(r) for r in reps]}


@router.post("/campaigns/{cid}/report")
def make_report(cid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    c = ctx.get(Campaign, cid)
    rep = reports.build(ctx.db, c)
    ctx.db.commit()
    return S.report(rep, with_body=True)


@router.get("/reports")
def list_reports(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(Report).where(Report.workspace_id == ctx.workspace.id)
                          .order_by(Report.created_at.desc()).limit(100)).scalars().all()
    return [S.report(r) for r in rows]


@router.get("/reports/{rid}")
def get_report(rid: int, ctx: Ctx = Depends(get_ctx)):
    return S.report(ctx.get(Report, rid), with_body=True)


@router.get("/reports/{rid}/download")
def download_report(rid: int, ctx: Ctx = Depends(get_ctx)):
    r = ctx.get(Report, rid)
    return PlainTextResponse(r.markdown, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="growthpilot-report-{r.id}.md"'})


@router.get("/experiments")
def list_experiments(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(Experiment).where(Experiment.workspace_id == ctx.workspace.id)
                          .order_by(Experiment.created_at.desc())).scalars().all()
    out = []
    for e in rows:
        d = S.experiment(e)
        d["hypothesis"] = S.hypothesis(e.hypothesis) if e.hypothesis else None
        d["variant_posts"] = {k: len(v) for k, v in exp_service.variant_data(ctx.db, e).items()}
        out.append(d)
    return out


@router.post("/experiments/{eid}/evaluate")
def evaluate(eid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    e = ctx.get(Experiment, eid)
    exp_service.evaluate(ctx.db, e)
    audit.record(ctx.db, "experiment.evaluated", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="experiment", target_id=e.id, ip=ctx.ip, conclusion=e.conclusion)
    ctx.db.commit()
    return S.experiment(e)


@router.get("/recommendations")
def list_recs(status: str = "", ctx: Ctx = Depends(get_ctx)):
    q = select(Recommendation).where(Recommendation.workspace_id == ctx.workspace.id)
    if status:
        q = q.where(Recommendation.status == status)
    return [S.recommendation(r) for r in ctx.db.execute(q.order_by(Recommendation.created_at.desc()).limit(100)).scalars()]


class RecStatusIn(BaseModel):
    status: str


@router.post("/recommendations/{rid}/status")
def rec_status(rid: int, body: RecStatusIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    if body.status not in ("open", "accepted", "dismissed"):
        raise ApiError(400, "Unknown status.", "validation")
    r = ctx.get(Recommendation, rid)
    r.status = body.status
    audit.record(ctx.db, "recommendation.status", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="recommendation", target_id=r.id, ip=ctx.ip, status=body.status)
    ctx.db.commit()
    return S.recommendation(r)
