from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from ... import audit, worker
from ...adapters import available_adapters
from ...agent.generation import SlotContentOut, get_generator, product_dict
from ...config import get_settings
from ...llm import LLMError, get_llm
from ...models import (
    Asset,
    Brand,
    Campaign,
    ChannelConnection,
    ContentItem,
    ContentStatus,
    Hypothesis,
    MetricSnapshot,
    Product,
    ResearchFinding,
    utcnow,
)
from ...services import content as workflow
from ...services import publishing
from ...services.errors import PermissionDenied, WorkflowError
from ...services.validation import final_caption, validate_item
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx, rate_limit
from .agent import maybe_auto_resume
from .brand import current_brand

router = APIRouter(prefix="/api", tags=["content"])


def _guard(fn):
    try:
        return fn()
    except PermissionDenied as exc:
        raise ApiError(403, str(exc), "forbidden") from exc
    except WorkflowError as exc:
        raise ApiError(400, str(exc), "workflow") from exc


def _to_utc(value: str, ctx: Ctx) -> datetime:
    try:
        d = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(400, "Invalid date/time.", "validation") from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=ctx.tz)
    return d.astimezone(UTC).replace(tzinfo=None)


def _detail(ctx: Ctx, item: ContentItem) -> dict:
    d = S.content(item, ctx.tz, full=True)
    assets = [ctx.db.get(Asset, i) for i in ([item.asset_id] if item.asset_id else []) + list(item.slide_asset_ids or [])]
    d["assets"] = [S.asset(a) for a in assets if a]
    prods = ctx.db.execute(select(Product).where(Product.id.in_(item.product_ids or [0]))).scalars().all()
    d["products"] = [S.product(p) for p in prods]
    d["final_caption"] = final_caption(item)
    return d


# ── list / create / edit ────────────────────────────────────────────────


@router.get("/content")
def list_content(status: str = "", campaign_id: int | None = None, platform: str = "", content_type: str = "",
                 q: str = "", ctx: Ctx = Depends(get_ctx)):
    query = select(ContentItem).where(ContentItem.workspace_id == ctx.workspace.id)
    if status:
        query = query.where(ContentItem.status.in_(status.split(",")))
    if campaign_id:
        query = query.where(ContentItem.campaign_id == campaign_id)
    if platform:
        query = query.where(ContentItem.platform == platform)
    if content_type:
        query = query.where(ContentItem.content_type == content_type)
    if q:
        like = f"%{q[:100]}%"
        query = query.where(or_(ContentItem.title.ilike(like), ContentItem.caption.ilike(like)))
    rows = ctx.db.execute(query.order_by(ContentItem.updated_at.desc()).limit(300)).scalars().all()
    return [S.content(i, ctx.tz) for i in rows]


class ContentIn(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    hook: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=5000)
    hashtags: list[str] | None = Field(default=None, max_length=40)
    cta: str | None = Field(default=None, max_length=255)
    image_brief: str | None = Field(default=None, max_length=5000)
    carousel_outline: list[str] | None = Field(default=None, max_length=20)
    video_script: str | None = Field(default=None, max_length=10000)
    content_type: str | None = None
    pillar: str | None = Field(default=None, max_length=120)
    product_ids: list[int] | None = None
    asset_id: int | None = None
    slide_asset_ids: list[int] | None = None
    planned_at: str | None = None
    note: str = Field(default="", max_length=1000)


def _changes(ctx: Ctx, body: ContentIn) -> dict:
    data = body.model_dump(exclude_unset=True)
    data.pop("note", None)
    if "planned_at" in data:
        data["planned_at"] = _to_utc(data["planned_at"], ctx) if data["planned_at"] else None
    for key in ("asset_id",):
        if data.get(key):
            ctx.get(Asset, data[key])
    for aid in data.get("slide_asset_ids") or []:
        ctx.get(Asset, aid)
    for pid in data.get("product_ids") or []:
        ctx.get(Product, pid)
    return data


class NewContentIn(ContentIn):
    platform: str = "instagram"
    campaign_id: int | None = None


@router.post("/content")
def create_content(body: NewContentIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    b = current_brand(ctx)
    if body.campaign_id:
        ctx.get(Campaign, body.campaign_id)
    if body.platform not in ("instagram", "pinterest", "facebook", "tiktok", "youtube"):
        raise ApiError(400, "Unknown platform.", "validation")
    item = ContentItem(workspace_id=ctx.workspace.id, brand_id=b.id, campaign_id=body.campaign_id,
                       platform=body.platform, created_by=ctx.user.id, generated_by="human")
    ctx.db.add(item)
    ctx.db.flush()
    workflow.add_revision(ctx.db, item, "human", ctx.user.id, "Created")
    changes = _changes(ctx, body)
    _guard(lambda: workflow.update(ctx.db, item, changes, user_id=ctx.user.id, role=ctx.role, ip=ctx.ip))
    ctx.db.commit()
    return _detail(ctx, item)


@router.get("/content/{cid}")
def get_content(cid: int, ctx: Ctx = Depends(get_ctx)):
    return _detail(ctx, ctx.get(ContentItem, cid))


@router.put("/content/{cid}")
def edit_content(cid: int, body: ContentIn, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    changes = _changes(ctx, body)
    _guard(lambda: workflow.update(ctx.db, item, changes, user_id=ctx.user.id, role=ctx.role, note=body.note,
                                   ip=ctx.ip))
    ctx.db.commit()
    return _detail(ctx, item)


class VersionIn(BaseModel):
    version: int


@router.post("/content/{cid}/restore")
def restore(cid: int, body: VersionIn, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    _guard(lambda: workflow.restore_revision(ctx.db, item, body.version, user_id=ctx.user.id, role=ctx.role))
    ctx.db.commit()
    return _detail(ctx, item)


class RegenIn(BaseModel):
    instructions: str = Field(default="", max_length=2000)


@router.post("/content/{cid}/regenerate")
def regenerate(cid: int, body: RegenIn, ctx: Ctx = Depends(get_ctx)):
    """Regenerate the caption as a new version (approval is reset if it had been approved)."""
    ctx.require_editor()
    rate_limit(f"regen:{ctx.workspace.id}", 60, 3600)
    item = ctx.get(ContentItem, cid)
    try:
        gen = get_generator(get_llm())
    except LLMError as exc:
        raise ApiError(400, str(exc), "llm_unavailable") from exc
    brand = ctx.db.get(Brand, item.brand_id)
    prods = [product_dict(p) for p in ctx.db.execute(select(Product).where(Product.id.in_(item.product_ids or [0]))).scalars()]
    brief = {"brand": {k: getattr(brand, k) for k in ("name", "description", "voice", "tone", "audience", "location",
                                                       "visual_guidelines", "approved_claims", "restricted_claims",
                                                       "prohibited_messaging")}, "geography": brand.location}
    current = {"title": item.title, "hook": item.hook, "caption": item.caption, "hashtags": item.hashtags,
               "cta": item.cta, "image_brief": item.image_brief, "carousel_outline": item.carousel_outline,
               "product_ids": item.product_ids}
    try:
        if body.instructions.strip() and not gen.is_mock:
            out, _ = gen.revise(brief, current, [{"message": body.instructions, "claim": ""}], prods)
        else:
            slot = {"index": item.version, "date": item.planned_at.isoformat() if item.planned_at else None,
                    "pillar": item.pillar or "Product spotlight", "content_type": item.content_type,
                    "variant": item.variant_label}
            out, _ = gen.slot_content(brief, slot, prods)
    except LLMError as exc:
        raise ApiError(502, str(exc), "llm_error") from exc
    assert isinstance(out, SlotContentOut)
    _guard(lambda: workflow.update(ctx.db, item, {"hook": out.hook, "caption": out.caption, "hashtags": out.hashtags,
                                                  "cta": out.cta, "image_brief": out.image_brief},
                                   user_id=ctx.user.id, role=ctx.role, source=gen.name,
                                   note=f"Regenerated{': ' + body.instructions[:200] if body.instructions else ''}"))
    item.rationale = out.rationale[:2000]
    validate_item(ctx.db, item)
    ctx.db.commit()
    return _detail(ctx, item) | {"generator": gen.name, "is_mock": gen.is_mock}


# ── workflow actions ─────────────────────────────────────────────────────


@router.post("/content/{cid}/validate")
def validate(cid: int, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    validate_item(ctx.db, item)
    ctx.db.commit()
    return item.validation


@router.post("/content/{cid}/submit")
def submit(cid: int, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    _guard(lambda: workflow.submit(ctx.db, item, user_id=ctx.user.id, role=ctx.role, ip=ctx.ip))
    ctx.db.commit()
    return _detail(ctx, item)


class ApproveIn(BaseModel):
    version: int
    acknowledge_warnings: bool = False
    authorize_publish: bool = False


@router.post("/content/{cid}/approve")
def approve(cid: int, body: ApproveIn, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    _guard(lambda: workflow.approve(ctx.db, item, user_id=ctx.user.id, role=ctx.role, version=body.version,
                                    acknowledge_warnings=body.acknowledge_warnings,
                                    authorize_publish=body.authorize_publish, ip=ctx.ip))
    ctx.db.commit()
    maybe_auto_resume(ctx.db, item)
    ctx.db.commit()
    return _detail(ctx, item)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/content/{cid}/request-changes")
def request_changes(cid: int, body: NoteIn, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    _guard(lambda: workflow.request_changes(ctx.db, item, user_id=ctx.user.id, role=ctx.role, note=body.note,
                                            ip=ctx.ip))
    ctx.db.commit()
    maybe_auto_resume(ctx.db, item)
    ctx.db.commit()
    return _detail(ctx, item)


@router.post("/content/{cid}/cancel")
def cancel(cid: int, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    _guard(lambda: workflow.cancel(ctx.db, item, user_id=ctx.user.id, role=ctx.role, ip=ctx.ip))
    ctx.db.commit()
    maybe_auto_resume(ctx.db, item)
    ctx.db.commit()
    return _detail(ctx, item)


class ScheduleIn(BaseModel):
    connection_id: int
    when: str | None = None  # ISO; naive values are in the workspace time zone; empty = planned time
    confirm: bool = False


@router.post("/content/{cid}/schedule")
def schedule(cid: int, body: ScheduleIn, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    conn = ctx.get(ChannelConnection, body.connection_id)
    when = _to_utc(body.when, ctx) if body.when else (item.planned_at if item.planned_at and item.planned_at > utcnow()
                                                      else utcnow() + timedelta(minutes=5))
    _guard(lambda: workflow.schedule(ctx.db, item, conn, when, user_id=ctx.user.id, role=ctx.role,
                                     confirmed=body.confirm, ip=ctx.ip))
    ctx.db.commit()
    worker.notify()
    return _detail(ctx, item)


@router.post("/content/{cid}/unschedule")
def unschedule(cid: int, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    _guard(lambda: workflow.unschedule(ctx.db, item, user_id=ctx.user.id, role=ctx.role, ip=ctx.ip))
    ctx.db.commit()
    return _detail(ctx, item)


class PublishNowIn(BaseModel):
    confirm: bool = False


@router.post("/content/{cid}/publish-now")
def publish_now(cid: int, body: PublishNowIn, ctx: Ctx = Depends(get_ctx)):
    """Publish a scheduled item immediately (owner only; live adapters need explicit confirmation)."""
    ctx.require_owner()
    item = ctx.get(ContentItem, cid)
    if item.status != ContentStatus.SCHEDULED:
        raise ApiError(400, "Only scheduled items can be published now.", "workflow")
    adapter = available_adapters().get(item.connection.adapter) if item.connection else None
    if adapter and adapter.external and not body.confirm:
        raise ApiError(400, "Confirm that this will publish to a real account.", "confirm_required")
    item.scheduled_at = utcnow()
    audit.record(ctx.db, "content.publish_now", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="content", target_id=item.id, ip=ctx.ip, live=bool(adapter and adapter.external))
    ctx.db.commit()
    publishing.publish_item(ctx.db, item.id, triggered_by=ctx.user.id)
    ctx.db.refresh(item)
    return _detail(ctx, item)


@router.post("/content/{cid}/verify")
def verify(cid: int, ctx: Ctx = Depends(get_ctx)):
    item = ctx.get(ContentItem, cid)
    state = publishing.verify(ctx.db, item)
    return {"state": state, "item": _detail(ctx, item)}


class ManualMetricsIn(BaseModel):
    reach: int | None = Field(default=None, ge=0)
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)


@router.post("/content/{cid}/metrics")
def manual_metrics(cid: int, body: ManualMetricsIn, ctx: Ctx = Depends(get_ctx)):
    """Record metrics read off the platform by hand (live mode). Demo mode refuses, to keep data separate."""
    ctx.require_editor()
    if get_settings().is_demo:
        raise ApiError(400, "Manual metrics are only accepted in live mode; demo metrics are synthetic.", "demo")
    item = ctx.get(ContentItem, cid)
    if item.status != ContentStatus.PUBLISHED:
        raise ApiError(400, "Only published content has metrics.", "workflow")
    ctx.db.add(MetricSnapshot(content_id=item.id, source="manual", **body.model_dump()))
    audit.record(ctx.db, "metrics.manual", workspace_id=ctx.workspace.id, user_id=ctx.user.id, target_type="content",
                 target_id=item.id, ip=ctx.ip)
    ctx.db.commit()
    return _detail(ctx, item)


# ── approval inbox & calendar ────────────────────────────────────────────


@router.get("/approvals")
def approvals(ctx: Ctx = Depends(get_ctx)):
    items = ctx.db.execute(select(ContentItem).where(ContentItem.workspace_id == ctx.workspace.id,
                                                     ContentItem.status == ContentStatus.IN_REVIEW)
                           .order_by(ContentItem.planned_at)).scalars().all()
    conns = ctx.db.execute(select(ChannelConnection).where(ChannelConnection.workspace_id == ctx.workspace.id)
                           ).scalars().all()
    allowed = available_adapters()
    out = []
    for i in items:
        validate_item(ctx.db, i)
        d = _detail(ctx, i)
        camp = i.campaign
        evidence = []
        if camp:
            h = ctx.db.execute(select(Hypothesis).where(Hypothesis.campaign_id == camp.id,
                                                        Hypothesis.selected.is_(True))).scalar_one_or_none()
            if h:
                d["hypothesis"] = S.hypothesis(h)
                evidence = [S.finding(f) for f in ctx.db.execute(select(ResearchFinding).where(
                    ResearchFinding.id.in_(h.evidence_ids or [0]))).scalars()]
            d["campaign"] = {"id": camp.id, "name": camp.name, "objective": camp.objective,
                             "success_criteria": camp.success_criteria}
        d["evidence"] = evidence
        d["target_connections"] = [S.connection(c) for c in conns if c.adapter in allowed
                                   and allowed[c.adapter].platform in ("any", i.platform)]
        out.append(d)
    ctx.db.commit()
    return {"items": out, "live_publishing_enabled": get_settings().live_publishing_enabled,
            "mode": get_settings().app_mode.value}


@router.get("/calendar")
def calendar(start: str, end: str, campaign_id: int | None = None, platform: str = "", status: str = "",
             content_type: str = "", ctx: Ctx = Depends(get_ctx)):
    s, e = _to_utc(start, ctx), _to_utc(end, ctx)
    if e <= s or e - s > timedelta(days=62):
        raise ApiError(400, "Choose a range of up to 62 days.", "validation")
    q = select(ContentItem).where(ContentItem.workspace_id == ctx.workspace.id, or_(
        ContentItem.planned_at.between(s, e), ContentItem.scheduled_at.between(s, e),
        ContentItem.published_at.between(s, e)))
    if campaign_id:
        q = q.where(ContentItem.campaign_id == campaign_id)
    if platform:
        q = q.where(ContentItem.platform == platform)
    if status:
        q = q.where(ContentItem.status.in_(status.split(",")))
    if content_type:
        q = q.where(ContentItem.content_type == content_type)
    rows = ctx.db.execute(q).scalars().all()
    return {"timezone": ctx.tz.key, "items": [S.content(i, ctx.tz) for i in rows]}
