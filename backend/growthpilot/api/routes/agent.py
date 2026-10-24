from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from ... import audit, worker
from ...agent.registry import REGISTRY, ROLE_LABELS
from ...agent.runner import FINISHED, create_run, pause_run, resume_run, retry_run, unpause_run
from ...demo.fixtures import DEMO_GOAL, EVAL_GOAL, SEVEN_PLATFORM_GOAL
from ...llm import LLMUnavailable
from ...models import AgentRun, ApprovalRequest, ContentItem, ContentStatus, RunStatus, UsageRecord
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx, rate_limit

router = APIRouter(prefix="/api/agent", tags=["agent"])

EXAMPLES = [
    DEMO_GOAL,
    SEVEN_PLATFORM_GOAL,
    "Research Deepavali shopping trends and identify content opportunities for our pooja essentials.",
    "Analyse public competitor content and identify topics they are covering that we are missing.",
    EVAL_GOAL,
]


class RunIn(BaseModel):
    goal: str = Field(min_length=5, max_length=4000)


@router.get("/tools")
def tools(ctx: Ctx = Depends(get_ctx)):
    return {"tools": [t.info() for t in REGISTRY.values()],
            "roles": [{"key": k.value, "label": v} for k, v in ROLE_LABELS.items()]}


@router.get("/examples")
def examples(ctx: Ctx = Depends(get_ctx)):
    return EXAMPLES


@router.post("/runs")
def start_run(body: RunIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    rate_limit(f"run:{ctx.workspace.id}", 20, 3600)
    active = ctx.db.execute(select(AgentRun).where(AgentRun.workspace_id == ctx.workspace.id,
                                                   AgentRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]))
                            ).scalars().first()
    if active:
        raise ApiError(409, "Another agent run is in progress. Wait for it or cancel it.", "busy")
    try:
        run = create_run(ctx.db, workspace_id=ctx.workspace.id, user_id=ctx.user.id, goal=body.goal)
    except LLMUnavailable as exc:
        raise ApiError(400, str(exc), "llm_unavailable") from exc
    ctx.db.commit()
    worker.notify()
    return S.run(run)


@router.get("/runs")
def list_runs(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(AgentRun).where(AgentRun.workspace_id == ctx.workspace.id)
                          .order_by(AgentRun.created_at.desc()).limit(50)).scalars().all()
    return [S.run(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str, after: int = 0, ctx: Ctx = Depends(get_ctx)):
    r = ctx.get(AgentRun, run_id)
    return S.run(r, with_steps=True, after_seq=after)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    r = ctx.get(AgentRun, run_id)
    if r.status in FINISHED:
        raise ApiError(400, "This run has already finished.", "finished")
    r.cancel_requested = True
    if r.status in (RunStatus.QUEUED, RunStatus.AWAITING_APPROVAL, RunStatus.PAUSED):
        r.status = RunStatus.CANCELLED
        r.completion_reason = "cancelled"
        r.outcome_summary = "Cancelled by a user."
    audit.record(ctx.db, "agent.run_cancelled", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="run", target_id=r.id, ip=ctx.ip)
    ctx.db.commit()
    return S.run(r)


@router.post("/runs/{run_id}/pause")
def pause(run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    r = ctx.get(AgentRun, run_id)
    if r.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise ApiError(400, "Only queued or running runs can be paused.", "not_running")
    pause_run(ctx.db, r)
    audit.record(ctx.db, "agent.run_paused", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="run", target_id=r.id, ip=ctx.ip)
    ctx.db.commit()
    return S.run(r)


@router.post("/runs/{run_id}/unpause")
def unpause(run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    r = ctx.get(AgentRun, run_id)
    if r.status != RunStatus.PAUSED:
        raise ApiError(400, "This run isn't paused.", "not_paused")
    unpause_run(ctx.db, r)
    audit.record(ctx.db, "agent.run_resumed", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="run", target_id=r.id, ip=ctx.ip)
    ctx.db.commit()
    worker.notify()
    return S.run(r)


@router.post("/runs/{run_id}/retry")
def retry(run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    r = ctx.get(AgentRun, run_id)
    if r.status not in (RunStatus.BLOCKED, RunStatus.FAILED):
        raise ApiError(400, "Only blocked or failed runs can be retried.", "not_retryable")
    try:
        retry_run(ctx.db, r)
    except LLMUnavailable as exc:
        raise ApiError(400, str(exc), "llm_unavailable") from exc
    audit.record(ctx.db, "agent.run_retried", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="run", target_id=r.id, ip=ctx.ip)
    ctx.db.commit()
    worker.notify()
    return S.run(r)


@router.get("/runs/{run_id}/usage")
def run_usage(run_id: str, ctx: Ctx = Depends(get_ctx)):
    r = ctx.get(AgentRun, run_id)
    rows = ctx.db.execute(select(UsageRecord).where(UsageRecord.run_id == r.id).order_by(UsageRecord.id)).scalars().all()
    reqs = ctx.db.execute(select(ApprovalRequest).where(ApprovalRequest.run_id == r.id)).scalars().all()
    return {"cost_usd": r.cost_usd, "budget_usd": r.cost_budget_usd,
            "approved_extra_usd": (r.state or {}).get("approved_extra_usd", 0.0),
            "records": [{"provider": u.provider, "operation": u.operation, "model": u.model,
                         "input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "units": u.units,
                         "cost_usd": u.cost_usd, "cached": u.cached, "created_at": S.dt(u.created_at)} for u in rows],
            "approval_requests": [S.approval_request(q) for q in reqs]}


def approval_note(ctx_db, run: AgentRun) -> str:
    ids = (run.state or {}).get("awaiting_ids", [])
    items = ctx_db.execute(select(ContentItem).where(ContentItem.id.in_(ids or [0]))).scalars().all()
    counts: dict[str, list[int]] = {}
    for i in items:
        counts.setdefault(i.status, []).append(i.id)
    return "; ".join(f"{k}: {', '.join('#' + str(x) for x in v)}" for k, v in counts.items()) or "no items"


@router.post("/runs/{run_id}/resume")
def resume(run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    r = ctx.get(AgentRun, run_id)
    if r.status != RunStatus.AWAITING_APPROVAL:
        raise ApiError(400, "This run isn't waiting for approval.", "not_waiting")
    resume_run(ctx.db, r, approval_note(ctx.db, r))
    ctx.db.commit()
    worker.notify()
    return S.run(r)


def maybe_auto_resume(db, item: ContentItem) -> None:
    """When the last item a paused run is waiting on has been reviewed, resume it."""
    if not item.run_id:
        return
    run = db.get(AgentRun, item.run_id)
    if run is None or run.status != RunStatus.AWAITING_APPROVAL:
        return
    ids = (run.state or {}).get("awaiting_ids", [])
    pending = db.execute(select(ContentItem.id).where(ContentItem.id.in_(ids or [0]),
                                                      ContentItem.status == ContentStatus.IN_REVIEW)).first()
    if pending is None:
        resume_run(db, run, approval_note(db, run))
        worker.notify()
