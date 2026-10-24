"""Deterministic orchestrator used in demo mode (no LLM).

It is a real state machine over real tool results. The orchestrator delegates each phase to a specialist role
(Research, Strategy, Creative, Verification, Distribution, Analyst), chooses the next step from the current
state, re-plans when a tool is blocked or fails, loops on verification failures, resolves conflicts between
roles (e.g. Strategy picked a channel that Distribution can't publish to), pauses for budget and human approval,
and can resume after a crash without redoing completed steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import REGISTRY, ROLE_LABELS, Role, ToolContext

MAX_REVISION_ROUNDS = 2


@dataclass
class Action:
    kind: str  # tool | finish | await_approval | await_budget | think
    tool: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    step_id: str | None = None
    reason: str = ""
    role: str = ""
    events: list[tuple[str, str]] = field(default_factory=list)  # logged just before the tool runs


def _s(i: int, tool: str, purpose: str, inp: dict | None = None, after_approval: bool = False) -> dict:
    role = REGISTRY[tool].role.value if tool in REGISTRY else Role.ORCHESTRATOR.value
    return {"id": f"s{i}", "tool": tool, "purpose": purpose, "input": inp or {}, "status": "pending",
            "after_approval": after_approval, "role": role}


def initial_plan(intent: str, params: dict, goal: str) -> list[dict]:
    cat = params.get("category")
    occ = params.get("occasion")
    geo = params.get("geography")
    platforms = params.get("platforms") or []
    steps: list[tuple] = []
    if intent == "campaign":
        q = " ".join(x for x in [cat, occ, "trends", geo or "India"] if x) or goal[:200]
        steps = [
            ("inspect_brand", "Understand the brand, its claims policy, channels and prior learnings."),
            ("retrieve_catalogue", "Find products that fit the goal, with their source and freshness.",
             {"query": goal[:300], "category": cat, "limit": 12}),
            ("verify_product_facts", "Check catalogue facts are fresh and fit to promote before planning.",
             {"scope": "catalogue"}),
            ("search_web", "Look for current, source-linked market signals.", {"query": q}),
            ("analyse_trends", "Add trend, festival and seasonal signals.", {"topic": f"{occ or cat or 'brand'}"}),
            ("collect_competitor_references", "Collect public competitor references (no private metrics)."),
            ("analyse_campaign_history", "Learn from past posts and experiments.", {"group_by": "pillar"}),
            ("identify_content_gaps", "Find under-served topics backed by evidence."),
            ("create_campaign_plan", "Turn the goal into a measurable strategy with competing hypotheses.",
             {"objective": goal[:1000], "days": params.get("days", 7), "platforms": platforms}),
            ("rank_campaign_ideas", "Prioritise hypotheses on evidence, fit, impact, cost, risk and feasibility."),
            ("estimate_campaign_cost", "Estimate AI and tool costs against the budgets before creating anything."),
            ("check_platform_capabilities", "Check which channels can publish what, and connection readiness."),
            ("prepare_schedule", "Build the calendar slots and the A/B experiment.",
             {"days": params.get("days", 7), "occasion": occ, "category": cat}),
            ("create_content_brief", "Write creative briefs from catalogue facts."),
            ("generate_caption", "Write hooks, captions, hashtags and CTAs."),
            ("generate_creative_asset", "Render the posters and carousel slides as real image files."),
            ("verify_product_facts", "Check every claim in captions against the catalogue.", {"scope": "content"}),
            ("validate_creative", "Check brand rules, platform rules and image quality."),
            ("create_platform_variant", "Adapt each post for the other channels in the plan."),
            ("verify_product_facts", "Check the channel variants' claims.", {"scope": "content", "variants": True}),
            ("validate_creative", "Check the channel variants' format and images.", {"variants": True}),
            ("request_human_approval", "Ask a person to approve each exact version."),
            ("prepare_schedule", "Schedule only what a person approved.", {"commit": True}, True),
        ]
    elif intent == "evaluate":
        steps = [
            ("inspect_brand", "Load brand and experiment context."),
            ("retrieve_available_analytics", "Pull the latest metrics the platforms make available."),
            ("analyse_campaign_history", "Compare performance by content type.", {"group_by": "content_type"}),
            ("analyse_campaign_history", "Compare performance by pillar.", {"group_by": "pillar"}),
            ("analyse_campaign_history", "Compare performance by platform.", {"group_by": "platform"}),
            ("evaluate_experiment", "Evaluate experiments against their success criteria and baselines."),
            ("recommend_next_action", "Recommend changes and plan the next experiment."),
            ("generate_campaign_report", "Write the campaign report."),
        ]
    elif intent == "research":
        steps = [
            ("inspect_brand", "Load brand context and permitted sources."),
            ("retrieve_catalogue", "See what the catalogue offers.", {"query": goal[:300], "limit": 12}),
            ("search_web", "Search for current, source-linked signals.", {"query": goal[:300]}),
            ("analyse_trends", "Add trend, festival and seasonal signals.", {"topic": goal[:200]}),
            ("collect_competitor_references", "Collect public competitor references."),
            ("identify_content_gaps", "Turn signals into evidence-backed opportunities."),
        ]
    elif intent == "competitor":
        steps = [
            ("inspect_brand", "Load brand context."),
            ("collect_competitor_references", "Collect and summarise public competitor references."),
            ("analyse_trends", "Get signals to compare against.", {"topic": cat or occ or "brand category"}),
            ("identify_content_gaps", "Find topics competitors are missing."),
        ]
    else:  # report
        steps = [("generate_campaign_report", "Write a report for the latest campaign.")]
    return [_s(i + 1, *t) for i, t in enumerate(steps)]


class DemoPlanner:
    name = "demo-planner"

    def start(self, ctx: ToolContext, intent: str, params: dict) -> tuple[list[dict], str]:
        plan = initial_plan(intent, params, ctx.run.goal)
        roles = []
        for s in plan:
            label = ROLE_LABELS[Role(s["role"])]
            if label not in roles:
                roles.append(label)
        return plan, (f"Intent: {intent}. Parameters: " + ", ".join(f"{k}={v}" for k, v in params.items() if v)
                      + f". Delegating to: {', '.join(roles)}.")

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
                                      "status": "pending", "after_approval": False, "inserted": True,
                                      "role": REGISTRY[tool].role.value})

    # ── loop ─────────────────────────────────────────────────────────────
    def next(self, ctx: ToolContext) -> Action:
        if ctx.state.get("need_budget"):
            bb = ctx.state.get("budget_block") or {}
            return Action("await_budget", message=bb.get("message", "A paid step needs more budget."))
        plan = self._plan(ctx)
        approved_phase = ctx.state.get("resumed_after_approval", False)
        last_role = ctx.state.get("last_role")
        for s in plan:
            if s["status"] != "pending":
                continue
            if s.get("after_approval") and not approved_phase:
                return Action("await_approval", message="Waiting for a person to review each post in the Approval "
                              "Inbox. Approved versions will be scheduled when the run resumes; nothing is published "
                              "without approval.")
            events = []
            if s.get("role") != last_role:
                ctx.remember("last_role", s.get("role"))
                events.append(("delegate", f"Orchestrator → {ROLE_LABELS[Role(s['role'])]}: {s['purpose']}"))
            return Action("tool", tool=s["tool"], input=dict(s.get("input") or {}), step_id=s["id"],
                          message=s["purpose"], role=s.get("role", ""), events=events)
        return Action("finish", message=self._summary(ctx), reason=ctx.state.get("finish_reason", "goal_achieved"))

    def observe(self, ctx: ToolContext, action: Action, status: str, result: Any, error: str) -> list[tuple[str, str]]:
        """Update the plan from a tool outcome. Returns (phase, message) events for the trace."""
        plan = self._plan(ctx)
        step = next(s for s in plan if s["id"] == action.step_id)
        step["status"] = {"ok": "done", "blocked": "blocked", "error": "failed"}[status]
        events: list[tuple[str, str]] = []
        tool = action.tool
        out = getattr(result, "output", {}) if result is not None else {}
        blockers = ctx.run.blockers or []

        if status == "blocked" and "budget" in blockers and (ctx.state.get("budget_block") or {}).get("tool") == tool:
            step["status"] = "pending"  # retried after an owner approves the budget
            ctx.remember("need_budget", True)
            events.append(("decision", f"{tool} needs more budget than this run has; asking an owner before "
                                       "spending."))
        elif status == "blocked":
            if tool == "search_web":
                events.append(("replan", f"Live search unavailable: {error.rstrip('.')}. The Research Agent switches "
                                         "to analyse_trends, which uses the store's own festival pages, the seasonal "
                                         "calendar and labelled fixtures; findings are marked as not live."))
            elif tool == "collect_competitor_references":
                sk = self._skip(plan, set(), "")
                events.append(("replan", f"{error} Gaps will rely on trend and catalogue signals only."
                               + (f" Skipped {', '.join(sk)}." if sk else "")))
            elif tool == "inspect_brand":
                self._skip(plan, {s["tool"] for s in plan}, "brand missing")
                ctx.remember("finish_reason", "blocked:brand_missing")
                events.append(("decision", f"Blocked: {error}"))
            elif tool == "prepare_schedule" and action.input.get("commit"):
                ctx.remember("finish_reason", "blocked:no_connection")
                events.append(("decision", f"Can't schedule: {error}"))
            elif tool == "estimate_campaign_cost":
                events.append(("decision", f"Cost check: {error}"))
            else:
                events.append(("replan", f"{tool} blocked: {error}. Continuing without it."))
        elif status == "error":
            if tool in ("retrieve_catalogue", "prepare_schedule", "create_campaign_plan") and not action.input.get("commit"):
                self._skip(plan, {s["tool"] for s in plan}, f"{tool} failed")
                ctx.remember("finish_reason", f"failed:{tool}")
                events.append(("decision", f"Stopping: {tool} failed ({error}). Use Retry once the cause is fixed."))
            elif tool == "evaluate_experiment":
                events.append(("replan", f"{error} Recommendations will be based on the comparisons only."))
            elif tool == "generate_campaign_report":
                events.append(("decision", f"No report: {error}"))
            else:
                events.append(("replan", f"{tool} failed ({error}); continuing with the rest of the plan."))
        else:
            events += self._after_ok(ctx, plan, step, tool, out, action)
        self._save(ctx, plan)
        return events

    def _after_ok(self, ctx, plan, step, tool, out, action) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if tool == "retrieve_catalogue" and not out.get("products"):
            self._skip(plan, {s["tool"] for s in plan if s["status"] == "pending"}, "no products")
            ctx.remember("finish_reason", "blocked:no_products")
            events.append(("decision", "No usable products in the catalogue, so the agent can't write factual "
                                       "content. Import or add products in Brand Brain."))
        if tool == "verify_product_facts" and action.input.get("scope") == "catalogue":
            excluded = out.get("excluded", [])
            if excluded:
                events.append(("decision", f"Verification Agent excluded {len(excluded)} product(s) from promotion: "
                               + "; ".join(f"{e['name']} ({e['reason']})" for e in excluded[:4])
                               + (" …" if len(excluded) > 4 else "") + "."))
            if out.get("no_photos"):
                events.append(("decision", f"{out['no_photos']} product(s) have no real product photo (the store "
                                           "lists generic stock images). The Creative Agent will use typographic "
                                           "product cards and never show a stock image as the product."))
            if not out.get("usable"):
                self._skip(plan, {s["tool"] for s in plan if s["status"] == "pending"}, "no promotable products")
                ctx.remember("finish_reason", "blocked:no_promotable_products")
                events.append(("decision", "No product passed the checks needed to promote it."))
        if tool == "identify_content_gaps" and not out.get("gaps"):
            events.append(("decision", "No clear gaps; hypotheses will focus on brand strengths and festival needs."))
        if tool == "retrieve_available_analytics" and not out.get("with_metrics"):
            sk = self._skip(plan, {"analyse_campaign_history", "evaluate_experiment"}, "no metrics")
            events.append(("replan", f"No posts have metrics yet; skipped {', '.join(sorted(set(sk)))}. "
                                     "Recommendations will say what to measure."))
        if tool == "estimate_campaign_cost":
            if out.get("over_budget"):
                events.append(("decision", f"Estimated cost ${out.get('estimated_usd', 0):.4f} is over the "
                                           f"remaining budget; paid steps will ask for approval when reached."))
        if tool == "check_platform_capabilities":
            dropped = [p for p in out.get("platforms", []) if not p.get("can_publish_images")]
            if dropped:
                names = ", ".join(p["label"] for p in dropped)
                events.append(("decision", f"Conflict resolved: the plan includes {names}, but the Distribution Agent "
                                           "reports they can't publish image posts. They get briefs only and won't be "
                                           "sent for publishing approval."))
                ctx.remember("brief_only_platforms", [p["platform"] for p in dropped])
            not_connected = [p["label"] for p in out.get("platforms", []) if not p.get("connected")]
            if not_connected:
                events.append(("decision", "Not connected: " + ", ".join(not_connected) + ". Variants will be prepared "
                                           "and approved, but can't be scheduled until connected."))
        if tool in ("validate_creative",):
            events += self._after_validation(ctx, plan, step, variants=bool(action.input.get("variants")))
        if tool == "request_human_approval":
            n = len(out.get("submitted", [])) + len(out.get("already_in_review", []))
            if n == 0:
                self._skip(plan, {"prepare_schedule"}, "nothing to approve")
                ctx.remember("finish_reason", "blocked:validation")
                events.append(("decision", "Nothing passed verification, so nothing was sent for approval. Edit the "
                                           "held items in Creative Studio."))
        return events

    def _after_validation(self, ctx: ToolContext, plan: list[dict], step: dict, variants: bool) -> list[tuple[str, str]]:
        fails = ctx.state.get("validation_failures", {})
        scope = set(ctx.state.get("variant_ids" if variants else "content_ids", []))
        keys = [k for k in fails if int(k.split(":")[1]) in scope]
        fixable = sorted({int(k.split(":")[1]) for k in keys if k.split(":")[0] in ("product_claims", "brand")})
        media = sorted({int(k.split(":")[1]) for k in keys if k.split(":")[0] in ("platform", "creative")})
        events = []
        key = "revision_rounds_variants" if variants else "revision_rounds"
        rounds = ctx.state.get(key, 0)
        if fixable and rounds < MAX_REVISION_ROUNDS:
            ctx.remember(key, rounds + 1)
            ids = {"content_ids": fixable}
            self._insert_after(plan, step["id"], [
                ("generate_caption", f"Creative Agent revises {len(fixable)} item(s) that failed verification "
                                     f"(round {rounds + 1}).", {"content_ids": fixable, "revise": True}),
                ("generate_creative_asset", "Re-render the revised items' images.", {"content_ids": fixable,
                                                                                     "rerender": True}),
                ("verify_product_facts", "Re-check product claims.", {"scope": "content", **ids}),
                ("validate_creative", "Re-check brand, platform and image rules.", {**ids, "variants": variants}),
            ])
            events.append(("replan", f"Verification Agent rejected {len(fixable)} item(s) "
                                     f"(#{', #'.join(map(str, fixable))}). Sending them back to the Creative Agent "
                                     "with the specific failures."))
        elif fixable:
            events.append(("decision", f"{len(fixable)} item(s) still fail after {rounds} revision round(s); they'll "
                                       "be held back for a person to edit."))
        if media:
            events.append(("decision", f"{len(media)} item(s) fail format or image checks that need a person or a "
                                       "different channel; they'll be held back."))
        if not fixable and not media:
            events.append(("evaluate", "All checked items pass verification."))
        return events

    # ── lifecycle hooks ──────────────────────────────────────────────────
    def resume(self, ctx: ToolContext, note: str) -> None:
        ctx.remember("resumed_after_approval", True)

    def on_budget(self, ctx: ToolContext, approved: bool) -> None:
        ctx.remember("need_budget", False)
        if not approved:
            tool = (ctx.state.get("budget_block") or {}).get("tool")
            plan = self._plan(ctx)
            for s in plan:
                if s["status"] == "pending" and s["tool"] == tool:
                    s["status"], s["note"] = "skipped", "budget declined"
                    break
            self._save(ctx, plan)

    def retry(self, ctx: ToolContext) -> None:
        """Re-run from the first failed/blocked step; steps skipped because of that stop run again too.
        Deliberate skips (budget declined, nothing to approve, no metrics) stay skipped."""
        keep = {"budget declined", "nothing to approve", "no metrics"}
        plan = self._plan(ctx)
        hit = False
        for s in plan:
            if s["status"] in ("failed", "blocked"):
                s["status"], hit = "pending", True
            elif hit and s["status"] == "skipped" and s.get("note") not in keep:
                s["status"] = "pending"
        ctx.remember("finish_reason", "goal_achieved")
        self._save(ctx, plan)

    def recover(self, ctx: ToolContext) -> None:
        """After a crash: every step is either recorded with its outcome or still pending, so just continue."""
        return None

    def _summary(self, ctx: ToolContext) -> str:
        st = ctx.state
        parts = []
        if st.get("campaign_id"):
            n_var = len(st.get("variant_ids", []))
            parts.append(f"Campaign #{st['campaign_id']} with {len(st.get('content_ids', []))} post(s)"
                         + (f" and {n_var} channel variant(s)" if n_var else "") + ".")
        if st.get("asset_ids"):
            parts.append(f"{len(st['asset_ids'])} image file(s) rendered.")
        if st.get("awaiting_ids"):
            parts.append(f"{len(st['awaiting_ids'])} item(s) went to the Approval Inbox.")
        if st.get("scheduled_ids"):
            parts.append(f"{len(st['scheduled_ids'])} approved item(s) scheduled.")
        if st.get("finding_ids"):
            parts.append(f"{len(st['finding_ids'])} research finding(s) recorded with provenance.")
        if st.get("evaluated_experiments"):
            parts.append("Experiments: " + "; ".join(f"{e['name'][:50]} → {e['conclusion']} (confidence "
                                                   f"{e.get('confidence') or 'n/a'})" for e in st["evaluated_experiments"]))
        if st.get("next_experiment_id"):
            parts.append(f"Next experiment planned (#{st['next_experiment_id']}).")
        if st.get("report_id"):
            parts.append(f"Report #{st['report_id']} generated.")
        cost = ctx.run.cost_usd or 0.0
        parts.append(f"Estimated provider cost: ${cost:.4f}" + (" (demo mode makes no paid calls)."
                                                                if ctx.settings.is_demo else "."))
        reason = st.get("finish_reason", "goal_achieved")
        if reason.startswith("blocked") or reason.startswith("failed"):
            parts.insert(0, f"Stopped early ({reason}).")
        return " ".join(parts) or "Done."
