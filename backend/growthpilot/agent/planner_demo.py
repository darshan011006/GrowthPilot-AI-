"""Deterministic planner used in demo mode (no LLM).

It is a real state machine over real tool results: it chooses tools from the goal and available data,
re-plans when a tool is blocked or fails, loops on validation failures, and pauses for human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import ToolContext

MAX_REVISION_ROUNDS = 2


@dataclass
class Action:
    kind: str  # tool | finish | await_approval | block
    tool: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    step_id: str | None = None
    reason: str = ""


def _s(i: int, tool: str, purpose: str, inp: dict | None = None, after_approval: bool = False) -> dict:
    return {"id": f"s{i}", "tool": tool, "purpose": purpose, "input": inp or {}, "status": "pending",
            "after_approval": after_approval}


def initial_plan(intent: str, params: dict, goal: str) -> list[dict]:
    cat = params.get("category") or ("sofa" if "sofa" in goal.lower() else None)
    occ = params.get("occasion")
    geo = params.get("geography")
    steps: list[tuple] = []
    if intent == "campaign":
        q = " ".join(x for x in [cat or "furniture", occ, "home decor trends", geo or "India"] if x)
        steps = [
            ("load_brand_context", "Understand the brand, claims policy and prior learnings."),
            ("retrieve_product_catalogue", "Get verified product facts for the featured category.", {"category": cat}),
            ("search_web", "Look for current, source-linked market signals.", {"query": q}),
            ("collect_trend_signals", "Add trend and seasonal signals.", {"topic": f"{cat or 'furniture'} and home interiors"}),
            ("fetch_competitor_data", "Collect public competitor content."),
            ("analyse_competitor_content", "Summarise what competitors cover."),
            ("identify_content_gaps", "Find under-served topics backed by evidence."),
            ("generate_campaign_hypotheses", "Propose competing, testable hypotheses.", {"objective": goal[:1000]}),
            ("rank_campaign_opportunities", "Pick the strongest hypothesis with stated criteria."),
            ("create_content_calendar", "Build the campaign, experiment and daily slots.",
             {"days": params.get("days", 7), "occasion": occ, "category": cat, "platform": params.get("platform", "instagram")}),
            ("generate_content_brief", "Write creative briefs from catalogue facts."),
            ("generate_caption", "Write captions, hooks, hashtags and CTAs."),
            ("generate_image_asset", "Attach product photos or labelled placeholders."),
            ("validate_product_claims", "Check every product claim against the catalogue."),
            ("validate_brand_consistency", "Check voice, prohibited messaging and originality."),
            ("validate_platform_constraints", "Check Instagram format rules."),
            ("request_approval", "Ask a person to approve each post."),
            ("schedule_publication", "Schedule what was approved.", {}, True),
        ]
    elif intent == "evaluate":
        steps = [
            ("load_brand_context", "Load brand and experiment context."),
            ("collect_post_analytics", "Pull the latest available metrics."),
            ("compare_content_performance", "Compare by content type.", {"group_by": "content_type"}),
            ("compare_content_performance", "Compare by pillar.", {"group_by": "pillar"}),
            ("evaluate_experiment", "Evaluate running experiments against their success criteria."),
            ("revise_marketing_strategy", "Recommend changes and plan the next experiment."),
            ("generate_campaign_report", "Write the campaign report."),
        ]
    elif intent == "research":
        steps = [
            ("load_brand_context", "Load brand context and permitted sources."),
            ("search_web", "Search for current, source-linked signals.", {"query": goal[:300]}),
            ("collect_trend_signals", "Add trend and seasonal signals.", {"topic": goal[:200]}),
            ("fetch_competitor_data", "Collect public competitor content."),
            ("analyse_competitor_content", "Summarise competitor coverage."),
            ("identify_content_gaps", "Turn signals into evidence-backed opportunities."),
        ]
    elif intent == "competitor":
        steps = [
            ("load_brand_context", "Load brand context."),
            ("fetch_competitor_data", "Collect public competitor content."),
            ("analyse_competitor_content", "Summarise themes, formats and CTAs."),
            ("collect_trend_signals", "Get trend signals to compare against.", {"topic": "furniture and home interiors"}),
            ("identify_content_gaps", "Find topics competitors are missing."),
        ]
    else:  # report
        steps = [("generate_campaign_report", "Write a report for the latest campaign.")]
    return [_s(i + 1, *t) for i, t in enumerate(steps)]


class DemoPlanner:
    name = "demo-planner"

    def start(self, ctx: ToolContext, intent: str, params: dict) -> tuple[list[dict], str]:
        plan = initial_plan(intent, params, ctx.run.goal)
        return plan, f"Intent: {intent}. Parameters: " + ", ".join(f"{k}={v}" for k, v in params.items() if v)

    # ── helpers ──────────────────────────────────────────────────────────
    def _plan(self, ctx) -> list[dict]:
        return [dict(s) for s in ctx.run.plan or []]

    def _save(self, ctx, plan) -> None:
        ctx.run.plan = plan

    def _skip(self, plan: list[dict], tools: set[str], reason: str) -> list[str]:
        skipped = []
        for s in plan:
            if s["status"] == "pending" and s["tool"] in tools:
                s["status"], s["note"] = "skipped", reason
                skipped.append(s["tool"])
        return skipped

    def _insert_after(self, plan: list[dict], step_id: str, new: list[tuple]) -> None:
        idx = next(i for i, s in enumerate(plan) if s["id"] == step_id)
        base = len(plan)
        for j, (tool, purpose, inp) in enumerate(new):
            plan.insert(idx + 1 + j, {"id": f"s{base + j + 1}", "tool": tool, "purpose": purpose, "input": inp,
                                      "status": "pending", "after_approval": False, "inserted": True})

    # ── loop ─────────────────────────────────────────────────────────────
    def next(self, ctx: ToolContext) -> Action:
        plan = self._plan(ctx)
        approved_phase = ctx.state.get("resumed_after_approval", False)
        for s in plan:
            if s["status"] != "pending":
                continue
            if s.get("after_approval") and not approved_phase:
                return Action("await_approval", message="Waiting for a person to review the posts in the Approval "
                              "Inbox. Approved items will be scheduled when the run resumes.")
            return Action("tool", tool=s["tool"], input=dict(s.get("input") or {}), step_id=s["id"],
                          message=s["purpose"])
        return Action("finish", message=self._summary(ctx), reason=ctx.state.get("finish_reason", "goal_achieved"))

    def observe(self, ctx: ToolContext, action: Action, status: str, result: Any, error: str) -> list[tuple[str, str]]:
        """Update the plan from a tool outcome. Returns (phase, message) events for the trace."""
        plan = self._plan(ctx)
        step = next(s for s in plan if s["id"] == action.step_id)
        step["status"] = {"ok": "done", "blocked": "blocked", "error": "failed"}[status]
        events: list[tuple[str, str]] = []
        tool = action.tool
        out = getattr(result, "output", {}) if result is not None else {}

        if status == "blocked":
            if tool == "search_web":
                events.append(("replan", f"Live search unavailable ({error}). Switching to collect_trend_signals, "
                                         "which uses the built-in calendar and labelled fixtures; findings will be "
                                         "marked as not live."))
            elif tool == "fetch_competitor_data":
                sk = self._skip(plan, {"analyse_competitor_content"}, "no competitor data")
                events.append(("replan", f"{error} Skipping {', '.join(sk) or 'competitor analysis'}; gaps will rely "
                                         "on trend signals only."))
            elif tool in ("load_brand_context",):
                self._skip(plan, {s["tool"] for s in plan}, "brand missing")
                ctx.remember("finish_reason", "blocked:brand_missing")
                events.append(("decision", f"Blocked: {error}"))
            elif tool == "schedule_publication":
                ctx.remember("finish_reason", "blocked:no_connection")
                events.append(("decision", f"Can't schedule: {error}"))
            else:
                events.append(("replan", f"{tool} blocked: {error}. Continuing without it."))
        elif status == "error":
            if tool == "retrieve_product_catalogue" or tool == "create_content_calendar":
                self._skip(plan, {s["tool"] for s in plan}, f"{tool} failed")
                ctx.remember("finish_reason", f"failed:{tool}")
                events.append(("decision", f"Stopping: {tool} failed ({error})."))
            elif tool == "evaluate_experiment":
                events.append(("replan", f"{error} Recommendations will be based on the comparisons only."))
            elif tool == "generate_campaign_report":
                events.append(("decision", f"No report: {error}"))
            else:
                events.append(("replan", f"{tool} failed ({error}); continuing with the rest of the plan."))
        else:
            if tool == "retrieve_product_catalogue" and not out.get("products"):
                self._skip(plan, {s["tool"] for s in plan if s["status"] == "pending"}, "no products")
                ctx.remember("finish_reason", "blocked:no_products")
                events.append(("decision", "No products in the catalogue, so the agent can't write factual content. "
                                           "Add products in Brand Brain."))
            if tool == "identify_content_gaps" and not out.get("gaps"):
                events.append(("decision", "No clear gaps; hypotheses will focus on brand strengths and trends."))
            if tool == "collect_post_analytics" and not out.get("with_metrics"):
                sk = self._skip(plan, {"compare_content_performance", "evaluate_experiment"}, "no metrics")
                events.append(("replan", f"No posts have metrics yet; skipped {', '.join(sorted(set(sk)))}. "
                                         "Recommendations will say what to measure."))
            if tool == "validate_platform_constraints":
                events += self._after_validation(ctx, plan, step)
            if tool == "request_approval":
                n = len(out.get("submitted", [])) + len(out.get("already_in_review", []))
                if n == 0:
                    self._skip(plan, {"schedule_publication"}, "nothing to approve")
                    ctx.remember("finish_reason", "blocked:validation")
                    events.append(("decision", "Nothing passed validation, so nothing was sent for approval. Edit the "
                                               "held items in Creative Studio."))
        self._save(ctx, plan)
        return events

    def _after_validation(self, ctx: ToolContext, plan: list[dict], step: dict) -> list[tuple[str, str]]:
        fails = ctx.state.get("validation_failures", {})
        fixable = sorted({int(k.split(":")[1]) for k in fails if k.split(":")[0] in ("product_claims", "brand")})
        media = sorted({int(k.split(":")[1]) for k in fails if k.startswith("platform:")})
        events = []
        rounds = ctx.state.get("revision_rounds", 0)
        if fixable and rounds < MAX_REVISION_ROUNDS:
            ctx.remember("revision_rounds", rounds + 1)
            ids = {"content_ids": fixable}
            self._insert_after(plan, step["id"], [
                ("generate_caption", f"Revise {len(fixable)} item(s) that failed validation (round {rounds + 1}).",
                 {"content_ids": fixable, "revise": True}),
                ("validate_product_claims", "Re-check product claims.", ids),
                ("validate_brand_consistency", "Re-check brand consistency.", ids),
                ("validate_platform_constraints", "Re-check platform rules.", ids),
            ])
            events.append(("replan", f"{len(fixable)} item(s) failed claim/brand checks "
                                     f"(#{', #'.join(map(str, fixable))}). Revising and re-validating."))
        elif fixable:
            events.append(("decision", f"{len(fixable)} item(s) still fail after {rounds} revision round(s); they'll "
                                       "be held back for a person to edit."))
        if media:
            events.append(("decision", f"{len(media)} item(s) fail platform checks that need a person (e.g. real "
                                       "product photos instead of placeholders); they'll be held back."))
        if not fixable and not media:
            events.append(("evaluate", "All items pass validation."))
        return events

    def resume(self, ctx: ToolContext, note: str) -> None:
        ctx.remember("resumed_after_approval", True)

    def _summary(self, ctx: ToolContext) -> str:
        st = ctx.state
        parts = []
        if st.get("campaign_id"):
            parts.append(f"Campaign #{st['campaign_id']} with {len(st.get('content_ids', []))} post(s).")
        if st.get("awaiting_ids"):
            parts.append(f"{len(st['awaiting_ids'])} post(s) went to the Approval Inbox.")
        if st.get("finding_ids"):
            parts.append(f"{len(st['finding_ids'])} research finding(s) recorded with provenance.")
        if st.get("evaluated_experiments"):
            parts.append("Experiments: " + "; ".join(f"{e['name'][:50]} → {e['conclusion']}"
                                                   for e in st["evaluated_experiments"]))
        if st.get("next_experiment_id"):
            parts.append(f"Next experiment planned (#{st['next_experiment_id']}).")
        if st.get("report_id"):
            parts.append(f"Report #{st['report_id']} generated.")
        reason = st.get("finish_reason", "goal_achieved")
        if reason.startswith("blocked") or reason.startswith("failed"):
            parts.insert(0, f"Stopped early ({reason}).")
        return " ".join(parts) or "Done."
