"""Strategy Agent tools: measurable plan with competing hypotheses, transparent ranking, cost estimate."""

from __future__ import annotations

from pydantic import Field
from sqlalchemy import select

from ... import usage
from ...config import get_settings
from ...creative.imagegen import image_price
from ...models import Campaign, Hypothesis, ResearchFinding, Workspace, utcnow
from ...platforms import ORDER, SPECS
from ...services import analytics
from ..registry import Effect, Permission, Role, ToolContext, ToolError, ToolInput, ToolResult, tool
from .common import brand, brief, generator

S = Role.STRATEGY
WEIGHTS = {"relevance": 0.15, "evidence_strength": 0.20, "product_fit": 0.15, "expected_value": 0.15,
           "cost": 0.10, "risk": 0.10, "feasibility": 0.15}
CLASS_POINTS = {"verified_observation": 3.0, "source_reported": 2.0, "inference": 1.0, "hypothesis": 0.5,
                "unknown": 0.0}


class PlanIn(ToolInput):
    objective: str = Field(default="", max_length=1000)
    days: int = Field(default=7, ge=1, le=14)
    platforms: list[str] = Field(default_factory=list, description="Platform keys; empty = brand preferences.")
    count: int = Field(default=3, ge=2, le=5, description="How many competing hypotheses.")
    budget_usd: float | None = Field(default=None, ge=0, le=1000)


@tool("create_campaign_plan", "Turn the goal into a measurable strategy: objective metric, audience, content pillars, "
      "a channel mix with reasons, success criteria, evaluation window and competing, evidence-linked hypotheses. "
      "Creates the campaign (planned) and the hypotheses.", PlanIn, Permission.DRAFT, role=S,
      effects=(Effect.LOCAL_WRITE, Effect.COST))
def create_campaign_plan(ctx: ToolContext, inp: PlanIn) -> ToolResult:
    b = brand(ctx)
    params = ctx.state.get("params", {})
    platforms = [p for p in (inp.platforms or params.get("platforms") or b.platform_preferences or ["instagram"])
                 if p in SPECS]
    platforms = sorted(dict.fromkeys(platforms), key=ORDER.index) or ["instagram"]
    if "instagram" in platforms:  # the A/B test runs on the primary channel
        platforms.remove("instagram")
        platforms.insert(0, "instagram")
    ids = ctx.state.get("finding_ids", [])
    findings = ctx.db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(ids or [0]),
                                                            ResearchFinding.workspace_id == ctx.workspace_id)
                              ).scalars().all()
    evidence = [{"id": f.id, "topic": f.topic, "statement": f.statement[:400], "classification": f.classification,
                 "source": f.source_url or f.source_title, "synthetic": f.is_synthetic} for f in findings]
    gen = generator(ctx)
    bf = brief(ctx)
    if inp.objective:
        bf["objective"] = inp.objective
    hyps, t1 = gen.hypotheses(bf, evidence, ctx.state.get("gaps", []), inp.count)
    plan, t2 = gen.campaign_plan(bf, {"statement": "selected by rank_campaign_ideas"},
                                 {"days": inp.days, "occasion": params.get("occasion"), "category": params.get("category"),
                                  "platforms": platforms})
    budget = inp.budget_usd if inp.budget_usd is not None else (b.campaign_budget_usd if b.campaign_budget_usd
                                                                is not None else None)
    camp = Campaign(workspace_id=ctx.workspace_id, brand_id=b.id, run_id=ctx.run.id, name=plan.name[:160],
                    objective=(inp.objective or ctx.run.goal)[:2000], audience=plan.audience or b.audience,
                    geography=params.get("geography") or b.location, platforms=platforms, pillars=plan.pillars,
                    creative_direction=plan.creative_direction, ctas=plan.ctas, measurement_plan=plan.measurement_plan,
                    success_criteria=[c.model_dump() | {"variant": "B", "baseline": "A"} for c in plan.success_criteria],
                    risks=plan.risks, assumptions=plan.assumptions, product_ids=ctx.state.get("product_ids", []),
                    objective_metric=plan.objective_metric, channel_mix=[c.model_dump() for c in plan.channel_mix],
                    evaluation_window_days=max(1, min(plan.evaluation_window_days, 60)), budget_usd=budget,
                    strategy={"hypotheses_requested": inp.count, "generator": gen.name,
                              "brand_snapshot": ctx.state.get("brand_snapshot")},
                    status="draft", created_by=ctx.run.created_by, is_synthetic=ctx.settings.is_demo)
    ctx.db.add(camp)
    ctx.db.flush()
    valid = {f.id for f in findings}
    created = []
    for h in hyps.hypotheses:
        hyp = Hypothesis(workspace_id=ctx.workspace_id, campaign_id=camp.id, run_id=ctx.run.id,
                         statement=h.statement[:2000], mechanism=h.mechanism[:2000],
                         evidence_ids=[i for i in h.evidence_ids if i in valid], uncertainty=h.uncertainty[:2000],
                         validation_method=h.validation_method[:2000],
                         scores={k: max(1, min(5, int(getattr(h, k)))) for k in
                                 ("relevance", "audience_fit", "brand_fit", "effort", "expected_value")})
        ctx.db.add(hyp)
        ctx.db.flush()
        created.append({"id": hyp.id, "statement": hyp.statement, "evidence_ids": hyp.evidence_ids,
                        "unlinked_evidence_dropped": len(h.evidence_ids) - len(hyp.evidence_ids)})
    ctx.remember("campaign_id", camp.id)
    ctx.remember("hypothesis_ids", [c["id"] for c in created])
    ctx.remember("platforms", platforms)
    ctx.run.campaign_id = camp.id
    mix = ", ".join(f"{c.platform} {c.share:.0%}" for c in plan.channel_mix)
    return ToolResult(
        f"Strategy “{camp.name}”: objective metric {plan.objective_metric}; channels {mix}; {len(plan.pillars)} pillars; "
        f"{len(created)} competing hypotheses; evaluate after {camp.evaluation_window_days} days.",
        {"campaign_id": camp.id, "objective_metric": plan.objective_metric, "channel_mix": camp.channel_mix,
         "pillars": plan.pillars, "success_criteria": camp.success_criteria, "hypotheses": created,
         "budget_usd": budget, "generator": gen.name}, is_mock=gen.is_mock, tokens=t1 + t2)


class RankIn(ToolInput):
    hypothesis_ids: list[int] = Field(default_factory=list)


@tool("rank_campaign_ideas", "Rank hypotheses with transparent weighted criteria: relevance, evidence strength "
      "(by evidence class), product fit, expected impact, cost, risk and feasibility. Scores are heuristics, not "
      "probabilities. Selects the top idea for the experiment.", RankIn, Permission.DRAFT, role=S,
      effects=(Effect.LOCAL_WRITE,))
def rank_campaign_ideas(ctx: ToolContext, inp: RankIn) -> ToolResult:
    ids = inp.hypothesis_ids or ctx.state.get("hypothesis_ids", [])
    hyps = ctx.db.execute(select(Hypothesis).where(Hypothesis.id.in_(ids or [0]),
                                                   Hypothesis.workspace_id == ctx.workspace_id)).scalars().all()
    if not hyps:
        raise ToolError("No hypotheses to rank. Run create_campaign_plan first.")
    n_products = len(ctx.state.get("product_ids", []))
    ranked = []
    for h in hyps:
        ev = ctx.db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(h.evidence_ids or [0]))).scalars().all()
        points = sum(CLASS_POINTS.get(e.classification, 0) * (0.5 if e.is_synthetic else 1.0) for e in ev)
        base = dict(h.scores or {})
        scores = {
            "relevance": float(base.get("relevance", 3)),
            "evidence_strength": round(max(1.0, min(5.0, 1 + points / 2)), 1),
            "product_fit": float(min(5, max(1, (base.get("brand_fit", 3) + (1 if n_products else -1))))),
            "expected_value": float(base.get("expected_value", 3)),
            "cost": float(base.get("effort", 3)),  # 5 = cheapest/least effort
            "risk": 4.0 if "price" not in h.statement.lower() else 3.0,  # price-led ideas depend on fresh data
            "feasibility": float(min(5, base.get("effort", 3) + (1 if n_products else 0))),
        }
        total = sum(WEIGHTS[k] * scores[k] for k in WEIGHTS)
        h.scores, h.total_score = scores | {"audience_fit": base.get("audience_fit")}, round(total, 2)
        ranked.append(h)
    ranked.sort(key=lambda h: h.total_score, reverse=True)
    for i, h in enumerate(ranked, start=1):
        h.rank, h.selected = i, i == 1
        h.status = "selected" if i == 1 else "proposed"
    top = ranked[0]
    ctx.remember("selected_hypothesis_id", top.id)
    rows = [{"id": h.id, "rank": h.rank, "total": h.total_score, "scores": h.scores, "statement": h.statement,
             "evidence_ids": h.evidence_ids} for h in ranked]
    gap = ranked[0].total_score - (ranked[1].total_score if len(ranked) > 1 else 0)
    note = "close call — consider testing both" if gap < 0.2 else "clear leader"
    return ToolResult(f"Selected #{top.id} (score {top.total_score:.2f}, {note}): {top.statement[:140]}",
                      {"ranking": rows, "weights": WEIGHTS, "method": "Weighted sum of 1–5 ratings. Evidence strength "
                       "= verified 3, source-reported 2, inference 1 point per item, halved for synthetic fixtures. "
                       "Cost and risk are scored so higher is better (cheaper, safer)."})


class CostIn(ToolInput):
    campaign_id: int | None = None
    ai_backgrounds: bool = Field(default=False, description="Include complete Gemini-generated post images in the estimate.")


@tool("estimate_campaign_cost", "Estimate provider costs for the rest of the campaign (LLM calls for briefs, captions "
      "and variants; searches; complete Gemini-generated post images) and compare with the run, campaign and monthly "
      "budgets. Local poster rendering is free when Gemini image generation is unavailable.", CostIn, Permission.READ,
      role=S, effects=(Effect.READ_ONLY,))
def estimate_campaign_cost(ctx: ToolContext, inp: CostIn) -> ToolResult:
    s = get_settings()
    cid = inp.campaign_id or ctx.state.get("campaign_id")
    camp = ctx.db.get(Campaign, cid) if cid else None
    params = ctx.state.get("params", {})
    days = int(params.get("days", 7))
    options = max(1, min(5, int(params.get("option_count", 1))))
    platforms = (camp.platforms if camp else None) or ctx.state.get("platforms") or ["instagram"]
    masters = days * options
    variants = masters * max(0, len(platforms) - 1)
    lines = []
    if s.is_demo:
        lines.append({"item": "All generation", "usd": 0.0, "note": "Demo generator and local rendering; no paid calls."})
    else:
        model = s.active_llm_model
        per_call = usage.token_cost(model, 3500, 1500)
        lines += [
            {"item": f"Briefs + captions ({masters} posts, ~2 calls each)", "usd": round(per_call * masters * 2, 4),
             "note": f"{model} at published prices"},
            {"item": f"Platform variants ({variants})", "usd": round(per_call * variants, 4), "note": model},
            {"item": "Revisions (allowance: 30% of posts)", "usd": round(per_call * max(1, masters * 0.3), 4),
             "note": model},
            {"item": "Planner turns (~15)", "usd": round(usage.token_cost(model, 12000, 1500) * 15, 4), "note": model},
        ]
        if inp.ai_backgrounds and s.image_generation_configured:
            price = image_price(s.campaign_image_model, s.campaign_image_size)
            lines.append({"item": f"Gemini post images ({masters})", "usd": round(price * masters, 4),
                          "note": f"{s.campaign_image_model} · {s.campaign_image_size}"})
    if not (not s.is_demo and inp.ai_backgrounds and s.image_generation_configured):
        lines.append({"item": "Poster rendering", "usd": 0.0, "note": "Local (Pillow); free."})
    est = round(sum(x["usd"] for x in lines), 4)
    ws = ctx.db.get(Workspace, ctx.workspace_id)
    run_spent = usage.spent(ctx.db, run_id=ctx.run.id)
    month_spent = usage.spent(ctx.db, workspace_id=ctx.workspace_id, since=usage.month_start(utcnow()))
    extra = float(ctx.state.get("approved_extra_usd", 0.0))
    remaining_run = ctx.run.cost_budget_usd + extra - run_spent
    over = est > remaining_run + 1e-9 or month_spent + est > ws.monthly_budget_usd + 1e-9
    if camp is not None:
        camp.budget_allocation = lines
        if camp.budget_usd is None:
            camp.budget_usd = round(max(est * 1.2, 0.0), 4) or None
    out = {"lines": lines, "estimated_usd": est, "run_remaining_usd": round(remaining_run, 4),
           "month_spent_usd": round(month_spent, 4), "monthly_budget_usd": ws.monthly_budget_usd,
           "over_budget": over, "prices_checked": usage.PRICES_CHECKED,
           "note": "Estimates from published prices; free tiers and credits are not deducted."}
    if over and not s.is_demo:
        raise usage.BudgetExceeded(f"Estimated campaign cost ${est:.4f} exceeds the remaining budget "
                                   f"(${remaining_run:.4f} for this run).", scope="run",
                                   needed_usd=round(est - max(remaining_run, 0), 4), budget_usd=ctx.run.cost_budget_usd,
                                   spent_usd=run_spent)
    return ToolResult(f"Estimated provider cost ${est:.4f} for {masters} post(s) and {variants} variant(s); "
                      f"${remaining_run:.4f} left in this run's budget.", out)


# Expose analytics baselines for planning tools in other modules.
baseline = analytics.baseline
