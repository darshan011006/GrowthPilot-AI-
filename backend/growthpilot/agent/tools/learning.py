"""Performance Analyst Agent tools: metrics, history, experiments, next action, reports."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from ...models import Campaign, Experiment, Recommendation
from ...services import analytics, experiments, reports
from ..registry import Effect, Permission, Role, ToolContext, ToolError, ToolInput, ToolResult, tool
from .common import brief, generator

A = Role.ANALYST


class AnalyticsIn(ToolInput):
    campaign_id: int | None = None
    force: bool = Field(default=True, description="Refresh even if metrics were collected recently.")


@tool("retrieve_available_analytics", "Pull the metrics each platform actually exposes for published posts (Instagram "
      "insights, Facebook public counts; synthetic metrics from demo adapters). Missing metrics stay missing.",
      AnalyticsIn, Permission.READ, role=A, effects=(Effect.EXTERNAL_READ, Effect.LOCAL_WRITE))
def retrieve_available_analytics(ctx: ToolContext, inp: AnalyticsIn) -> ToolResult:
    ids = None
    if inp.campaign_id:
        c = ctx.db.get(Campaign, inp.campaign_id)
        if c is None or c.workspace_id != ctx.workspace_id:
            raise ToolError("Campaign not found.")
        ids = [i.id for i in c.items] or [0]
    stats = analytics.collect(ctx.db, ctx.workspace_id, item_ids=ids, force=inp.force)
    s = analytics.summary(ctx.db, ctx.workspace_id, inp.campaign_id)
    synthetic = s["data_source"] in ("synthetic", "mixed")
    return ToolResult(
        f"Collected {stats['collected']} new snapshot(s); {s['with_metrics']}/{s['published']} published post(s) have "
        f"metrics ({s['data_source']} data)." + (f" {len(stats['errors'])} error(s)." if stats["errors"] else ""),
        {"collection": stats, "with_metrics": s["with_metrics"], "published": s["published"],
         "data_source": s["data_source"], "freshness": s["freshness"]}, is_mock=synthetic)


class HistoryIn(ToolInput):
    campaign_id: int | None = None
    group_by: Literal["content_type", "pillar", "platform", "campaign"] = "content_type"


@tool("analyse_campaign_history", "Compare past performance by content type, pillar, platform or campaign "
      "(engagement rate and saves per reach, with sample sizes and caveats), and list prior experiment learnings.",
      HistoryIn, Permission.READ, role=A, effects=(Effect.READ_ONLY,))
def analyse_campaign_history(ctx: ToolContext, inp: HistoryIn) -> ToolResult:
    s = analytics.summary(ctx.db, ctx.workspace_id, inp.campaign_id)
    groups = s[f"by_{inp.group_by}"]
    ctx.remember(f"compare_{inp.group_by}", groups)
    learned = [{"id": e.id, "name": e.name, "conclusion": e.conclusion, "learnings": e.learnings[:300]}
               for e in ctx.db.execute(select(Experiment).where(Experiment.workspace_id == ctx.workspace_id,
                                                                Experiment.conclusion != "")).scalars()]
    caveats = ["Groups differ in topic, timing and creative; this is not a controlled comparison."]
    if any(g["n"] < 3 for g in groups):
        caveats.append("Some groups have fewer than 3 posts; differences may be noise.")
    if s["data_source"] == "synthetic":
        caveats.append("SYNTHETIC demo metrics.")
    if not groups:
        return ToolResult("No posts with metrics to compare yet.", {"groups": [], "caveats": caveats,
                                                                     "experiments": learned})
    top = groups[0]
    return ToolResult(
        f"By {inp.group_by}: {top['key']} leads at {top['mean_engagement_rate']:.1%} mean engagement rate "
        f"(n={top['n']})" + (f"; lowest {groups[-1]['key']} {groups[-1]['mean_engagement_rate']:.1%} "
                             f"(n={groups[-1]['n']})" if len(groups) > 1 else "") + ".",
        {"groups": groups, "metric": analytics.METRIC_DEFINITIONS["engagement_rate_by_reach"], "caveats": caveats,
         "data_source": s["data_source"], "experiments": learned}, is_mock=s["data_source"] == "synthetic")


class EvaluateIn(ToolInput):
    experiment_ids: list[int] = Field(default_factory=list, description="Empty = all running experiments.")


@tool("evaluate_experiment", "Evaluate experiments within one platform against their success criteria and the "
      "brand's earlier posts: sample-size check, permutation test, lift, confidence level. Reports supported / not "
      "supported / inconclusive with association language only.", EvaluateIn, Permission.DRAFT, role=A,
      effects=(Effect.LOCAL_WRITE,))
def evaluate_experiment(ctx: ToolContext, inp: EvaluateIn) -> ToolResult:
    q = select(Experiment).where(Experiment.workspace_id == ctx.workspace_id)
    q = q.where(Experiment.id.in_(inp.experiment_ids)) if inp.experiment_ids else q.where(
        Experiment.status.in_(["running", "planned"]))
    exps = ctx.db.execute(q).scalars().all()
    if not exps:
        raise ToolError("No experiments to evaluate.")
    out, skipped = [], []
    for e in exps:
        if not any(experiments.variant_data(ctx.db, e).values()):
            skipped.append(e.name)
            continue
        r = experiments.evaluate(ctx.db, e)
        winner = r.get("challenger") if r["conclusion"] == "supported" else (
            r.get("baseline") if r["conclusion"] == "not_supported" else None)
        out.append({"id": e.id, "name": e.name, "conclusion": r["conclusion"], "learnings": r["learnings"],
                    "next_recommendation": r["next_recommendation"], "data_source": r["data_source"],
                    "per_variant": r["per_variant"], "lift": r.get("lift"), "p_value": r.get("p_value"),
                    "confidence": e.confidence, "per_variant_winner": winner, "platform": r.get("platform"),
                    "vs_historical_baseline": r.get("vs_historical_baseline")})
    ctx.remember("evaluated_experiments", out)
    if not out:
        raise ToolError("No experiment has published posts yet" + (f" ({'; '.join(skipped)[:200]})" if skipped else "") + ".")
    synthetic = any(o["data_source"] == "synthetic" for o in out)
    return ToolResult("; ".join(f"“{o['name'][:60]}”: {o['conclusion']} (confidence {o['confidence'] or 'n/a'})"
                                for o in out), {"experiments": out, "skipped_no_data": skipped}, is_mock=synthetic)


class NextIn(ToolInput):
    campaign_id: int | None = None


@tool("recommend_next_action", "Turn evaluated experiments and comparisons into prioritised recommendations, each "
      "with evidence, uncertainty and one concrete proposed change (pillar focus, cadence, channel mix, product focus "
      "or creative style) that an owner can approve, and plan the next experiment.", NextIn, Permission.DRAFT,
      role=A, effects=(Effect.LOCAL_WRITE, Effect.COST))
def recommend_next_action(ctx: ToolContext, inp: NextIn) -> ToolResult:
    evals = ctx.state.get("evaluated_experiments", [])
    s = analytics.summary(ctx.db, ctx.workspace_id, inp.campaign_id)
    findings = {"experiments": evals, "by_content_type": ctx.state.get("compare_content_type") or s["by_content_type"],
                "by_pillar": ctx.state.get("compare_pillar") or s["by_pillar"],
                "by_platform": ctx.state.get("compare_platform") or s["by_platform"], "data_source": s["data_source"]}
    gen = generator(ctx)
    out, tokens = gen.strategy_revision(brief(ctx), findings)
    synthetic = s["data_source"] in ("synthetic", "mixed")
    camp_id = inp.campaign_id or next((e.campaign_id for e in ctx.db.execute(select(Experiment).where(
        Experiment.id.in_([e["id"] for e in evals] or [0]))).scalars()), None)
    recs = []
    for r in out.recommendations:
        change = r.proposed_change.model_dump()
        rec = Recommendation(workspace_id=ctx.workspace_id, campaign_id=camp_id, run_id=ctx.run.id,
                             title=r.title[:255], detail=r.detail[:4000], rationale=r.rationale[:4000],
                             uncertainty=r.uncertainty[:2000], priority=r.priority if r.priority in
                             ("high", "medium", "low") else "medium", is_synthetic=synthetic,
                             proposed_change=change if change.get("type") != "none" else {},
                             evidence=[{"type": "experiment", "ref": e["id"], "summary": f"{e['conclusion']} "
                                        f"(confidence {e.get('confidence') or 'n/a'})"} for e in evals]
                             + [{"type": "comparison", "ref": k, "summary": f"{g['key']}: "
                                 f"{g['mean_engagement_rate']:.1%} (n={g['n']})"}
                                for k in ("by_pillar", "by_platform") for g in (findings[k] or [])[:2]])
        ctx.db.add(rec)
        recs.append({"title": r.title, "proposed_change": change})
    nx = out.next_experiment
    exp = Experiment(workspace_id=ctx.workspace_id, campaign_id=camp_id, name=nx.name[:200],
                     variants=[{"label": "A", "description": nx.variant_a}, {"label": "B", "description": nx.variant_b}],
                     primary_metric="saves_per_reach", intervention=nx.hypothesis,
                     success_criteria=[{"metric": "saves_per_reach", "comparator": "relative_lift_gte", "target": 0.15,
                                        "variant": "B", "baseline": "A"}], status="planned", is_synthetic=synthetic,
                     learnings=f"Proposed hypothesis: {nx.hypothesis}")
    ctx.db.add(exp)
    ctx.db.flush()
    ctx.remember("next_experiment_id", exp.id)
    actionable = sum(1 for r in recs if r["proposed_change"].get("type") not in (None, "none"))
    return ToolResult(f"{len(recs)} recommendation(s), {actionable} with a change awaiting owner approval; next "
                      f"experiment planned: “{nx.name}”.",
                      {"recommendations": recs, "next_experiment_id": exp.id, "generator": gen.name},
                      is_mock=gen.is_mock or synthetic, tokens=tokens)


class ReportIn(ToolInput):
    campaign_id: int | None = None


@tool("generate_campaign_report", "Generate a Markdown campaign report: objectives, hypotheses, evidence, content per "
      "platform, approvals, publishing history, observed performance, experiment results, costs and next steps.",
      ReportIn, Permission.DRAFT, role=A, effects=(Effect.LOCAL_WRITE,))
def generate_campaign_report(ctx: ToolContext, inp: ReportIn) -> ToolResult:
    cid = inp.campaign_id or ctx.state.get("campaign_id") or ctx.run.campaign_id
    if not cid:
        ev = ctx.state.get("evaluated_experiments") or []
        cid = next((e.campaign_id for e in ctx.db.execute(select(Experiment).where(
            Experiment.id.in_([e["id"] for e in ev] or [0]))).scalars() if e.campaign_id), None)
    camp = ctx.db.get(Campaign, cid) if cid else None
    if camp is None or camp.workspace_id != ctx.workspace_id:
        raise ToolError("No campaign to report on.")
    rep = reports.build(ctx.db, camp, ctx.run.id)
    ctx.remember("report_id", rep.id)
    return ToolResult(f"Report #{rep.id} generated for “{camp.name}” ({rep.data_source} performance data).",
                      {"report_id": rep.id, "campaign_id": camp.id, "data_source": rep.data_source},
                      is_mock=rep.data_source == "synthetic")
