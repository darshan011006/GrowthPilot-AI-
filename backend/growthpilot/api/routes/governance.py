"""Human control surfaces: non-content approval requests, recommendations, usage and budgets."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from ... import audit, usage, worker
from ...agent.runner import decide_budget, resume_run
from ...models import AgentRun, ApprovalRequest, Brand, Recommendation, RunStatus, UsageRecord, utcnow
from ...platforms import ORDER
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx

router = APIRouter(prefix="/api", tags=["governance"])


@router.get("/approval-requests")
def list_requests(status: str = "pending", ctx: Ctx = Depends(get_ctx)):
    q = select(ApprovalRequest).where(ApprovalRequest.workspace_id == ctx.workspace.id)
    if status:
        q = q.where(ApprovalRequest.status == status)
    return [S.approval_request(r) for r in ctx.db.execute(q.order_by(ApprovalRequest.requested_at.desc())
                                                          .limit(100)).scalars()]


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=2000)


@router.post("/approval-requests/{rid}/decide")
def decide(rid: int, body: DecideIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    req = ctx.get(ApprovalRequest, rid)
    if req.status != "pending":
        raise ApiError(400, "This request has already been decided.", "decided")
    if req.kind == "budget":
        decide_budget(ctx.db, req, body.approve, ctx.user.id, body.note)
    else:
        req.status = "approved" if body.approve else "rejected"
        req.decided_by, req.decided_at, req.decision_note = ctx.user.id, utcnow(), body.note[:2000]
        audit.record(ctx.db, "approval.decided", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip,
                     target_type="approval_request", target_id=req.id, kind=req.kind, approved=body.approve)
        run = ctx.db.get(AgentRun, req.run_id) if req.run_id else None
        if run and run.status == RunStatus.AWAITING_APPROVAL:
            pending = ctx.db.execute(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id,
                                                                   ApprovalRequest.status == "pending")).first()
            if pending is None:
                resume_run(ctx.db, run, f"{req.kind.replace('_', ' ')} request #{req.id} "
                           f"{'approved' if body.approve else 'rejected'}" + (f": {body.note}" if body.note else ""))
    ctx.db.commit()
    worker.notify()
    return S.approval_request(req)


# ── recommendations ──────────────────────────────────────────────────────


def _apply_change(b: Brand, change: dict) -> str:
    kind, value = change.get("type"), str(change.get("value") or "")
    if kind == "pillar_focus" and value:
        pillars = [p for p in (b.content_pillars or []) if p.lower() != value.lower()]
        b.content_pillars = [value, *pillars]
        return f"“{value}” is now the first content pillar."
    if kind == "channel_mix" and value in ORDER:
        prefs = [p for p in (b.platform_preferences or list(ORDER)) if p != value]
        b.platform_preferences = [*prefs, value]
        return f"{value} moved to the end of the platform preferences."
    if kind == "cadence" and value.isdigit():
        b.posting_constraints = dict(b.posting_constraints or {}) | {"max_posts_per_day": max(1, min(int(value), 5))}
        return f"Posting cadence set to at most {value} post(s) a day."
    if kind in ("creative_style", "product_focus") and value:
        key = "preferred_variant" if kind == "creative_style" else "focus_products"
        b.posting_constraints = dict(b.posting_constraints or {}) | {key: value}
        return f"Saved {kind.replace('_', ' ')}: {value}."
    raise ApiError(400, "This recommendation has no change that can be applied automatically.", "not_applicable")


@router.post("/recommendations/{rid}/apply")
def apply_recommendation(rid: int, ctx: Ctx = Depends(get_ctx)):
    """An owner approves the agent's proposed change; it's applied to the brand profile and audited."""
    ctx.require_owner()
    r = ctx.get(Recommendation, rid)
    if r.status in ("applied", "dismissed"):
        raise ApiError(400, f"This recommendation is already {r.status}.", "decided")
    b = ctx.db.execute(select(Brand).where(Brand.workspace_id == ctx.workspace.id).order_by(Brand.id)).scalars().first()
    if b is None:
        raise ApiError(404, "No brand.", "no_brand")
    msg = _apply_change(b, r.proposed_change or {})
    r.status, r.decided_by, r.decided_at = "applied", ctx.user.id, utcnow()
    audit.record(ctx.db, "recommendation.applied", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip,
                 target_type="recommendation", target_id=r.id, change=r.proposed_change, result=msg)
    ctx.db.commit()
    return S.recommendation(r) | {"message": msg}


# ── usage & budgets ──────────────────────────────────────────────────────


@router.get("/usage")
def usage_summary(ctx: Ctx = Depends(get_ctx)):
    s = usage.summary(ctx.db, ctx.workspace.id)
    recent = ctx.db.execute(select(UsageRecord).where(UsageRecord.workspace_id == ctx.workspace.id)
                            .order_by(UsageRecord.id.desc()).limit(50)).scalars().all()
    runs = ctx.db.execute(select(AgentRun).where(AgentRun.workspace_id == ctx.workspace.id)
                          .order_by(AgentRun.created_at.desc()).limit(10)).scalars().all()
    return s | {"recent": [{"provider": u.provider, "operation": u.operation, "model": u.model, "run_id": u.run_id,
                            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "units": u.units,
                            "cost_usd": u.cost_usd, "cached": u.cached, "created_at": S.dt(u.created_at)}
                           for u in recent],
                "runs": [{"id": r.id, "goal": r.goal[:120], "status": r.status, "cost_usd": r.cost_usd,
                          "budget_usd": r.cost_budget_usd, "tokens": r.tokens_used, "created_at": S.dt(r.created_at)}
                         for r in runs]}
