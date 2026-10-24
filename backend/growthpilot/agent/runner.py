"""Agent run execution: Observe → Plan → Select tool → Execute → Inspect → Evaluate → Replan or finish.

Every step is persisted as an ``AgentStep`` and committed immediately, so the Command Centre shows real
progress by polling. Limits: max steps, token budget, wall-clock deadline, cancellation, bounded retries.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..llm import LLMError, LLMUnavailable, get_llm
from ..models import AgentRun, AgentStep, Brand, Membership, RunStatus, Workspace, utcnow
from ..security import redact
from . import tools as _tools  # noqa: F401 - registers tools
from .intent import parse_goal
from .planner_demo import Action, DemoPlanner
from .planner_llm import LLMPlanner
from .registry import ToolBlocked, ToolContext, ToolError, ToolResult, get_tool

log = logging.getLogger(__name__)

MAX_RETRIES = 2
_sleep = time.sleep


def set_sleep(fn) -> None:
    global _sleep
    _sleep = fn


def _json(v: Any) -> Any:
    """Truncate large values for storage in the trace."""
    import json

    text = json.dumps(v, default=str, ensure_ascii=False)
    if len(text) <= 20000:
        return json.loads(text)
    return {"truncated": True, "preview": text[:20000]}


def create_run(db: Session, *, workspace_id: int, user_id: int | None, goal: str, brand_id: int | None = None) -> AgentRun:
    s = get_settings()
    ws = db.get(Workspace, workspace_id)
    if brand_id is None:
        brand_id = db.execute(select(Brand.id).where(Brand.workspace_id == workspace_id).order_by(Brand.id)
                              .limit(1)).scalar_one_or_none()
    if s.is_live:
        llm = get_llm()  # raises LLMUnavailable with a clear message
        planner = llm.name
    else:
        planner = DemoPlanner.name
    intent, params = parse_goal(goal)
    run = AgentRun(workspace_id=workspace_id, brand_id=brand_id, goal=goal.strip()[:4000], intent=intent,
                   planner=planner, status=RunStatus.QUEUED, max_steps=ws.agent_max_steps,
                   token_budget=ws.agent_token_budget, created_by=user_id, state={"params": params})
    db.add(run)
    db.flush()
    audit.record(db, "agent.run_created", workspace_id=workspace_id, user_id=user_id, target_type="run",
                 target_id=run.id, intent=intent, planner=planner)
    return run


class Runner:
    def __init__(self, db: Session, run: AgentRun):
        self.db = db
        self.run = run
        role = "editor"
        if run.created_by:
            m = db.execute(select(Membership).where(Membership.user_id == run.created_by,
                                                    Membership.workspace_id == run.workspace_id)).scalar_one_or_none()
            role = m.role if m else "viewer"
        self.ctx = ToolContext(db=db, run=run, workspace_id=run.workspace_id, brand_id=run.brand_id,
                               settings=get_settings(), user_role=role)
        if run.planner == DemoPlanner.name:
            self.planner = DemoPlanner()
        else:
            llm = get_llm()
            if llm is None:
                raise LLMUnavailable("This run needs an LLM but the app is in demo mode.")
            self.planner = LLMPlanner(llm)

    # ── trace ────────────────────────────────────────────────────────────
    def step(self, phase: str, message: str, *, tool: str | None = None, inp: Any = None, out: Any = None,
             status: str = "ok", is_mock: bool = False, attempt: int = 1, duration_ms: int = 0, tokens: int = 0) -> None:
        self.run.step_count += 1 if phase == "tool" else 0
        seq = (self.db.execute(select(AgentStep.seq).where(AgentStep.run_id == self.run.id)
                               .order_by(AgentStep.seq.desc()).limit(1)).scalar_one_or_none() or 0) + 1
        self.db.add(AgentStep(run_id=self.run.id, seq=seq, phase=phase, tool=tool, message=redact(message)[:8000]
                              if message else "", input=_json(inp) if inp is not None else None,
                              output=_json(out) if out is not None else None, status=status, is_mock=is_mock,
                              attempt=attempt, duration_ms=duration_ms, tokens=tokens))
        self.run.heartbeat_at = utcnow()
        self.db.commit()

    def _finish(self, status: str, reason: str, summary: str) -> None:
        self.run.status = status
        self.run.completion_reason = reason[:60]
        self.run.outcome_summary = summary[:8000]
        self.run.finished_at = utcnow()
        self.step("finish", summary, status="ok" if status == RunStatus.COMPLETED else "blocked")
        audit.record(self.db, "agent.run_finished", workspace_id=self.run.workspace_id, target_type="run",
                     target_id=self.run.id, status=status, reason=reason)
        self.db.commit()

    def _limits(self) -> str | None:
        self.db.refresh(self.run, ["cancel_requested"])
        if self.run.cancel_requested:
            return "cancelled"
        if self.run.step_count >= self.run.max_steps:
            return "step_limit"
        if self.run.tokens_used >= self.run.token_budget:
            return "token_budget"
        if self.run.deadline_at and utcnow() > self.run.deadline_at:
            return "timeout"
        return None

    # ── tool execution ───────────────────────────────────────────────────
    def execute(self, action: Action) -> tuple[str, ToolResult | None, str]:
        try:
            tool = get_tool(action.tool or "")
        except ToolError as exc:
            self.step("tool", str(exc), tool=action.tool, inp=action.input, status="error")
            return "error", None, str(exc)
        try:
            inp = tool.input_model.model_validate(action.input or {})
        except ValidationError as exc:
            msg = "Invalid tool input: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
            self.step("tool", msg, tool=tool.name, inp=action.input, status="error")
            return "error", None, msg
        attempt = 0
        while True:
            attempt += 1
            t0 = time.monotonic()
            try:
                result = tool.fn(self.ctx, inp)
                self.db.flush()
            except ToolBlocked as exc:
                self.db.rollback()
                ms = int((time.monotonic() - t0) * 1000)
                blockers = list(self.run.blockers or [])
                if exc.blocker not in blockers:
                    blockers.append(exc.blocker)
                self.run.blockers = blockers
                self.step("tool", f"Blocked: {exc}", tool=tool.name, inp=inp.model_dump(mode="json"), status="blocked",
                          attempt=attempt, duration_ms=ms)
                return "blocked", None, str(exc)
            except (ToolError, LLMError) as exc:
                self.db.rollback()
                ms = int((time.monotonic() - t0) * 1000)
                retry = getattr(exc, "retryable", False) and attempt <= MAX_RETRIES
                self.step("tool", f"{'Retrying after error' if retry else 'Error'}: {exc}", tool=tool.name,
                          inp=inp.model_dump(mode="json"), status="error", attempt=attempt, duration_ms=ms)
                if retry:
                    _sleep(min(2 ** attempt, 8))
                    continue
                return "error", None, str(exc)
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                log.exception("tool %s crashed", tool.name)
                self.step("tool", f"Unexpected error in {tool.name}: {type(exc).__name__}", tool=tool.name,
                          inp=inp.model_dump(mode="json"), status="error", attempt=attempt)
                return "error", None, f"internal error ({type(exc).__name__})"
            ms = int((time.monotonic() - t0) * 1000)
            self.run.tokens_used += result.tokens
            self.step("tool", result.summary, tool=tool.name, inp=inp.model_dump(mode="json"), out=result.output,
                      is_mock=result.is_mock, attempt=attempt, duration_ms=ms, tokens=result.tokens)
            return "ok", result, ""

    # ── main loop ────────────────────────────────────────────────────────
    def run_until_pause(self) -> None:
        r = self.run
        if r.status == RunStatus.QUEUED and not r.started_at:
            r.started_at = utcnow()
            ws = self.db.get(Workspace, r.workspace_id)
            r.deadline_at = utcnow() + timedelta(minutes=ws.agent_timeout_minutes)
            r.status = RunStatus.RUNNING
            self.step("observe", f"Goal received: “{r.goal}”. Mode: {self.ctx.settings.app_mode.value}; planner: "
                      f"{r.planner}." + (" Demo mode uses fixtures and a mock Instagram adapter; nothing leaves this "
                                         "machine." if self.ctx.settings.is_demo else ""))
            plan, note = self.planner.start(self.ctx, r.intent, (r.state or {}).get("params", {}))
            r.plan = plan if r.planner == DemoPlanner.name else plan
            self.step("plan", note + "\n" + "\n".join(f"{i + 1}. {s['tool']} — {s['purpose']}"
                                                     for i, s in enumerate(plan)))
        else:
            r.status = RunStatus.RUNNING
            self.db.commit()
        while True:
            stop = self._limits()
            if stop:
                status = RunStatus.CANCELLED if stop == "cancelled" else RunStatus.BLOCKED
                msg = {"cancelled": "Cancelled by a user.", "step_limit": f"Stopped: reached the {r.max_steps}-step "
                       "limit.", "token_budget": f"Stopped: token budget ({r.token_budget:,}) used.",
                       "timeout": "Stopped: run exceeded its time limit."}[stop]
                self._finish(status, stop, msg)
                return
            try:
                res = self.planner.next(self.ctx)
            except LLMError as exc:
                self._finish(RunStatus.FAILED, "llm_error", f"The planner model failed: {exc}")
                return
            if isinstance(res, tuple):  # LLM planner made a model call
                _action, events, tokens = res
                r.tokens_used += tokens
                for phase, msg in events:
                    self.step(phase, msg, tokens=tokens)
                    tokens = 0
                if not events:
                    self.db.commit()
                continue
            action = res
            if action.kind == "await_approval":
                r.status = RunStatus.AWAITING_APPROVAL
                self.step("approval", action.message)
                return
            if action.kind == "finish":
                reason = action.reason or "goal_achieved"
                status = RunStatus.COMPLETED if not reason.startswith(("blocked", "failed")) else RunStatus.BLOCKED
                self._finish(status, reason, action.message)
                return
            self.db.commit()  # persist planner bookkeeping so a tool-error rollback can't undo it
            status, result, error = self.execute(action)
            for phase, msg in self.planner.observe(self.ctx, action, status, result, error):
                self.step(phase, msg)
            self.db.commit()


def claim_next_run(db: Session) -> AgentRun | None:
    rid = db.execute(select(AgentRun.id).where(AgentRun.status == RunStatus.QUEUED).order_by(AgentRun.created_at)
                     .limit(1)).scalar_one_or_none()
    if rid is None:
        return None
    res = db.execute(update(AgentRun).where(AgentRun.id == rid, AgentRun.status == RunStatus.QUEUED)
                     .values(status=RunStatus.RUNNING, heartbeat_at=utcnow()))
    db.commit()
    if res.rowcount != 1:
        return None
    run = db.get(AgentRun, rid)
    db.refresh(run)
    return run


def execute_run(db: Session, run: AgentRun) -> AgentRun:
    """Run (or resume) until it finishes or pauses. Never raises."""
    try:
        if run.status == RunStatus.RUNNING and not run.started_at:
            run.status = RunStatus.QUEUED  # let run_until_pause initialise it
        Runner(db, run).run_until_pause()
    except LLMUnavailable as exc:
        db.rollback()
        run = db.get(AgentRun, run.id)
        run.status, run.error, run.completion_reason, run.finished_at = RunStatus.BLOCKED, str(exc), "llm_unavailable", utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run %s crashed", run.id)
        db.rollback()
        run = db.get(AgentRun, run.id)
        run.status, run.error, run.completion_reason = RunStatus.FAILED, f"Internal error ({type(exc).__name__}).", "crash"
        run.finished_at = utcnow()
        db.commit()
    return run


def resume_run(db: Session, run: AgentRun, note: str) -> None:
    if run.status != RunStatus.AWAITING_APPROVAL:
        return
    runner = Runner(db, run)
    runner.planner.resume(runner.ctx, note)
    run.status = RunStatus.QUEUED
    runner.step("approval", f"Resumed: {note}")


def recover_stale(db: Session) -> None:
    cutoff = utcnow() - timedelta(minutes=10)
    for run in db.execute(select(AgentRun).where(AgentRun.status == RunStatus.RUNNING,
                                                 AgentRun.heartbeat_at < cutoff)).scalars().all():
        run.status, run.completion_reason, run.finished_at = RunStatus.FAILED, "worker_stopped", utcnow()
        run.error = "The worker stopped while this run was in progress. Start a new run."
    db.commit()
