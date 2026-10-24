from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select

from ...models import Campaign, ContentItem, Experiment, Hypothesis, ResearchFinding, Workspace
from ...services import seasonal
from ...services.content import add_revision
from ..registry import Permission, ToolContext, ToolError, ToolInput, ToolResult, tool
from .common import brand, brief, generator

WEIGHTS = {"relevance": 0.20, "evidence_strength": 0.25, "audience_fit": 0.20, "brand_fit": 0.15, "effort": 0.10,
           "expected_value": 0.10}
CLASS_POINTS = {"verified_observation": 3.0, "source_reported": 2.0, "inference": 1.0, "hypothesis": 0.5,
                "unknown": 0.0}


class HypothesesIn(ToolInput):
    objective: str = Field(default="", max_length=1000)
    count: int = Field(default=3, ge=2, le=5)


@tool("generate_campaign_hypotheses", "Generate competing, testable campaign hypotheses, each linked to evidence ids, "
      "with mechanism, uncertainty and a validation method.", HypothesesIn, Permission.DRAFT)
def generate_campaign_hypotheses(ctx: ToolContext, inp: HypothesesIn) -> ToolResult:
    brand(ctx)
    ids = ctx.state.get("finding_ids", [])
    findings = ctx.db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(ids),
                                                            ResearchFinding.workspace_id == ctx.workspace_id)
                              ).scalars().all() if ids else []
    evidence = [{"id": f.id, "topic": f.topic, "statement": f.statement, "classification": f.classification,
                 "source": f.source_url or f.source_title, "synthetic": f.is_synthetic} for f in findings]
    gen = generator(ctx)
    b = brief(ctx)
    if inp.objective:
        b["objective"] = inp.objective
    out, tokens = gen.hypotheses(b, evidence, ctx.state.get("gaps", []), inp.count)
    valid = {f.id for f in findings}
    created = []
    for h in out.hypotheses:
        hyp = Hypothesis(workspace_id=ctx.workspace_id, run_id=ctx.run.id, statement=h.statement[:2000],
                         mechanism=h.mechanism[:2000], evidence_ids=[i for i in h.evidence_ids if i in valid],
                         uncertainty=h.uncertainty[:2000], validation_method=h.validation_method[:2000],
                         scores={k: max(1, min(5, int(getattr(h, k)))) for k in
                                 ("relevance", "audience_fit", "brand_fit", "effort", "expected_value")})
        ctx.db.add(hyp)
        ctx.db.flush()
        dropped = len(h.evidence_ids) - len(hyp.evidence_ids)
        created.append({"id": hyp.id, "statement": hyp.statement, "evidence_ids": hyp.evidence_ids,
                        "unlinked_evidence_dropped": dropped})
    ctx.remember("hypothesis_ids", [c["id"] for c in created])
    return ToolResult(f"{len(created)} hypotheses proposed.", {"hypotheses": created, "generator": gen.name},
                      is_mock=gen.is_mock, tokens=tokens)


class RankIn(ToolInput):
    hypothesis_ids: list[int] = Field(default_factory=list)


@tool("rank_campaign_opportunities", "Rank hypotheses with transparent weighted criteria (relevance, evidence strength, "
      "audience fit, brand fit, effort, expected value). Scores are heuristics, not probabilities.", RankIn,
      Permission.DRAFT)
def rank_campaign_opportunities(ctx: ToolContext, inp: RankIn) -> ToolResult:
    ids = inp.hypothesis_ids or ctx.state.get("hypothesis_ids", [])
    hyps = ctx.db.execute(select(Hypothesis).where(Hypothesis.id.in_(ids),
                                                   Hypothesis.workspace_id == ctx.workspace_id)).scalars().all()
    if not hyps:
        raise ToolError("No hypotheses to rank. Run generate_campaign_hypotheses first.")
    ranked = []
    for h in hyps:
        ev = ctx.db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(h.evidence_ids or [0]))).scalars().all()
        points = sum(CLASS_POINTS.get(e.classification, 0) * (0.5 if e.is_synthetic else 1.0) for e in ev)
        strength = max(1.0, min(5.0, 1 + points / 2))
        scores = dict(h.scores or {})
        scores["evidence_strength"] = round(strength, 1)
        total = sum(WEIGHTS[k] * float(scores.get(k, 3)) for k in WEIGHTS)
        h.scores, h.total_score = scores, round(total, 2)
        ranked.append(h)
    ranked.sort(key=lambda h: h.total_score, reverse=True)
    for i, h in enumerate(ranked, start=1):
        h.rank, h.selected = i, i == 1
        h.status = "selected" if i == 1 else "proposed"
    top = ranked[0]
    ctx.remember("selected_hypothesis_id", top.id)
    rows = [{"id": h.id, "rank": h.rank, "total": h.total_score, "scores": h.scores, "statement": h.statement,
             "evidence_count": len(h.evidence_ids or [])} for h in ranked]
    gap = ranked[0].total_score - (ranked[1].total_score if len(ranked) > 1 else 0)
    note = "close call — consider testing both" if gap < 0.2 else "clear leader"
    return ToolResult(f"Selected #{top.id} (score {top.total_score:.2f}, {note}): {top.statement[:140]}",
                      {"ranking": rows, "weights": WEIGHTS, "method": "Weighted sum of 1–5 ratings. Evidence strength "
                       "= verified 3, source-reported 2, inference 1 point per item, halved for synthetic fixtures."})


class CalendarIn(ToolInput):
    days: int = Field(default=7, ge=1, le=14)
    start_date: date | None = None
    platform: str = Field(default="instagram")
    hypothesis_id: int | None = None
    occasion: str | None = None
    category: str | None = None


def _slot_time(day: date, idx: int, tz: ZoneInfo) -> datetime:
    local = datetime.combine(day, time(13, 0) if idx % 2 == 0 else time(19, 30), tzinfo=tz)
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


@tool("create_content_calendar", "Create the campaign, an A/B experiment for the selected hypothesis, and one draft "
      "slot per day (post or carousel) at planned times in the workspace time zone.", CalendarIn, Permission.DRAFT)
def create_content_calendar(ctx: ToolContext, inp: CalendarIn) -> ToolResult:
    b = brand(ctx)
    params = ctx.state.get("params", {})
    hyp_id = inp.hypothesis_id or ctx.state.get("selected_hypothesis_id")
    hyp = ctx.db.get(Hypothesis, hyp_id) if hyp_id else None
    if hyp is not None and hyp.workspace_id != ctx.workspace_id:
        hyp = None
    ws = ctx.db.get(Workspace, ctx.workspace_id)
    tz = ZoneInfo(ws.timezone or "UTC")
    today_local = datetime.now(tz).date()
    start = max(inp.start_date or today_local + timedelta(days=1), today_local)
    occasion = inp.occasion or params.get("occasion")
    category = inp.category or params.get("category") or "sofa"
    gen = generator(ctx)
    plan, tokens = gen.campaign_plan(brief(ctx), {"statement": hyp.statement if hyp else "",
                                                  "validation_method": hyp.validation_method if hyp else ""},
                                     {"days": inp.days, "occasion": occasion, "category": category,
                                      "platform": inp.platform})
    camp = Campaign(workspace_id=ctx.workspace_id, brand_id=b.id, run_id=ctx.run.id, name=plan.name[:160],
                    objective=ctx.run.goal[:2000], audience=b.audience, geography=params.get("geography") or b.location,
                    start_date=start, end_date=start + timedelta(days=inp.days - 1), platforms=[inp.platform],
                    pillars=plan.pillars, creative_direction=plan.creative_direction, ctas=plan.ctas,
                    measurement_plan=plan.measurement_plan,
                    success_criteria=[c.model_dump() | {"variant": "B", "baseline": "A"} for c in plan.success_criteria],
                    risks=plan.risks, assumptions=plan.assumptions, product_ids=ctx.state.get("product_ids", []),
                    status="planned", created_by=ctx.run.created_by, is_synthetic=ctx.settings.is_demo)
    ctx.db.add(camp)
    ctx.db.flush()
    if hyp:
        hyp.campaign_id = camp.id
        for hid in ctx.state.get("hypothesis_ids", []):
            other = ctx.db.get(Hypothesis, hid)
            if other and other.workspace_id == ctx.workspace_id:
                other.campaign_id = camp.id
    exp = Experiment(workspace_id=ctx.workspace_id, campaign_id=camp.id, hypothesis_id=hyp.id if hyp else None,
                     name=f"{camp.name}: carousel planning posts (B) vs single product posts (A)",
                     variants=[{"label": "A", "description": "Single-image product post (control)"},
                               {"label": "B", "description": "Carousel following the selected hypothesis"}],
                     success_criteria=camp.success_criteria, min_sample_per_variant=3, status="planned",
                     is_synthetic=ctx.settings.is_demo)
    ctx.db.add(exp)
    ctx.db.flush()
    occ_day = None
    if occasion:
        for o in seasonal.upcoming(today_local, within_days=120):
            if occasion.lower() in o["name"].lower():
                occ_day = o["start"]
                break
    b_pillars = ["Small-space solutions", "Styling tips"]
    a_pillars = ["Product spotlight", "Craft & materials"] + (["Festive"] if occasion else [])
    prod_ids = ctx.state.get("product_ids", []) or camp.product_ids
    ids, festive_used = [], False
    for d in range(inp.days):
        day = start + timedelta(days=d)
        variant = "B" if d % 2 == 0 else "A"
        if variant == "B":
            pillar, ctype = b_pillars[(d // 2) % len(b_pillars)], "carousel"
        else:
            pillar, ctype = a_pillars[(d // 2) % len(a_pillars)], "post"
            if occasion and not festive_used and (occ_day is None or day >= occ_day - timedelta(days=10)):
                pillar, festive_used = "Festive", True
        item = ContentItem(workspace_id=ctx.workspace_id, brand_id=b.id, campaign_id=camp.id, experiment_id=exp.id,
                           variant_label=variant, run_id=ctx.run.id, platform=inp.platform, content_type=ctype,
                           pillar=pillar, title=f"Day {d + 1}: {pillar}", planned_at=_slot_time(day, d, tz),
                           product_ids=[prod_ids[d % len(prod_ids)]] if prod_ids else [],
                           generated_by=gen.name, created_by=ctx.run.created_by, is_synthetic=ctx.settings.is_demo)
        ctx.db.add(item)
        ctx.db.flush()
        add_revision(ctx.db, item, gen.name, None, "Calendar slot created")
        ids.append(item.id)
    ctx.remember("campaign_id", camp.id)
    ctx.remember("experiment_id", exp.id)
    ctx.remember("content_ids", ids)
    ctx.run.campaign_id = camp.id
    return ToolResult(
        f"Created “{camp.name}” ({start:%d %b}–{camp.end_date:%d %b}, {tz.key}) with {len(ids)} slots and experiment "
        f"#{exp.id}. Posting times 13:00/19:30 local are a starting heuristic, not measured best times.",
        {"campaign_id": camp.id, "experiment_id": exp.id, "content_ids": ids, "pillars": camp.pillars,
         "timezone": tz.key}, is_mock=gen.is_mock, tokens=tokens)
