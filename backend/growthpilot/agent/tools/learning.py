from __future__ import annotations

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from ...models import Campaign, Experiment, Recommendation
from ...services import analytics, experiments, reports
from ..registry import Permission, ToolContext, ToolError, ToolInput, ToolResult, tool
from .common import brief, generator


class AnalyticsIn(ToolInput):
    campaign_id: int | None = None
    force: bool = Field(default=True, description="Refresh even if metrics were collected recently.")


@tool("collect_post_analytics", "Pull available metrics for published posts from their adapters (Instagram insights "
      "in live mode; synthetic metrics from the demo adapter). Missing metrics stay missing.", AnalyticsIn,
      Permission.READ)
def collect_post_analytics(ctx: ToolContext, inp: AnalyticsIn) -> ToolResult:
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


class CompareIn(ToolInput):
    campaign_id: int | None = None
    group_by: Literal["content_type", "pillar", "platform", "campaign"] = "content_type"


@tool("compare_content_performance", "Compare engagement rate by reach across content types, pillars, platforms or "
      "campaigns, with sample sizes and caveats.", CompareIn, Permission.READ)
def compare_content_performance(ctx: ToolContext, inp: CompareIn) -> ToolResult:
    s = analytics.summary(ctx.db, ctx.workspace_id, inp.campaign_id)
    groups = s[f"by_{inp.group_by}"]
    ctx.remember(f"compare_{inp.group_by}", groups)
    caveats = ["Groups differ in topic, timing and creative; this is not a controlled comparison."]
    if any(g["n"] < 3 for g in groups):
        caveats.append("Some groups have fewer than 3 posts; differences may be noise.")
    if s["data_source"] == "synthetic":
        caveats.append("SYNTHETIC demo metrics.")
    if not groups:
        return ToolResult("No posts with metrics to compare yet.", {"groups": [], "caveats": caveats})
    top = groups[0]
    return ToolResult(
        f"By {inp.group_by}: {top['key']} leads at {top['mean_engagement_rate']:.1%} mean engagement rate "
        f"(n={top['n']})" + (f"; lowest {groups[-1]['key']} {groups[-1]['mean_engagement_rate']:.1%} "
                             f"(n={groups[-1]['n']})" if len(groups) > 1 else "") + ".",
        {"groups": groups, "metric": analytics.METRIC_DEFINITIONS["engagement_rate_by_reach"], "caveats": caveats,
         "data_source": s["data_source"]}, is_mock=s["data_source"] == "synthetic")


class EvaluateIn(ToolInput):
    experiment_ids: list[int] = Field(default_factory=list, description="Empty = all running experiments.")


@tool("evaluate_experiment", "Evaluate experiments against their success criteria with a sample-size check and a "
      "permutation test. Reports supported / not supported / inconclusive and what is still uncertain.", EvaluateIn,
      Permission.DRAFT)
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
            skipped.append(e.name)  # nothing published yet: leave it untouched
            continue
        r = experiments.evaluate(ctx.db, e)
        out.append({"id": e.id, "name": e.name, "conclusion": r["conclusion"], "learnings": r["learnings"],
                    "next_recommendation": r["next_recommendation"], "data_source": r["data_source"],
                    "per_variant": r["per_variant"], "lift": r.get("lift"), "p_value": r.get("p_value")})
    ctx.remember("evaluated_experiments", out)
    if not out:
        raise ToolError("No experiment has published posts yet" + (f" ({'; '.join(skipped)[:200]})" if skipped else "") + ".")
    synthetic = all(o["data_source"] in ("synthetic", "none") for o in out)
    return ToolResult("; ".join(f"“{o['name'][:60]}”: {o['conclusion']}" for o in out) or "Nothing evaluated.",
                      {"experiments": out, "skipped_no_data": skipped}, is_mock=synthetic and any(o["data_source"] == "synthetic" for o in out))


class ReviseIn(ToolInput):
    campaign_id: int | None = None


@tool("revise_marketing_strategy", "Turn evaluated experiments and performance comparisons into prioritised "
      "recommendations with evidence and uncertainty, and plan the next experiment.", ReviseIn, Permission.DRAFT)
def revise_marketing_strategy(ctx: ToolContext, inp: ReviseIn) -> ToolResult:
    evals = ctx.state.get("evaluated_experiments", [])
    groups = ctx.state.get("compare_content_type") or analytics.summary(ctx.db, ctx.workspace_id)["by_content_type"]
    s = analytics.summary(ctx.db, ctx.workspace_id, inp.campaign_id)
    findings = {"experiments": evals, "by_content_type": groups, "by_pillar": s["by_pillar"],
                "data_source": s["data_source"]}
    gen = generator(ctx)
    out, tokens = gen.strategy_revision(brief(ctx), findings)
    synthetic = s["data_source"] in ("synthetic", "mixed")
    camp_id = inp.campaign_id or next((e.campaign_id for e in ctx.db.execute(select(Experiment).where(
        Experiment.id.in_([e["id"] for e in evals] or [0]))).scalars()), None)
    recs = []
    for r in out.recommendations:
        rec = Recommendation(workspace_id=ctx.workspace_id, campaign_id=camp_id, run_id=ctx.run.id,
                             title=r.title[:255], detail=r.detail[:4000], rationale=r.rationale[:4000],
                             uncertainty=r.uncertainty[:2000], priority=r.priority if r.priority in
                             ("high", "medium", "low") else "medium", is_synthetic=synthetic,
                             evidence=[{"type": "experiment", "ref": e["id"], "summary": e["conclusion"]} for e in evals]
                             + [{"type": "comparison", "ref": "content_type", "summary":
                                 f"{g['key']}: {g['mean_engagement_rate']:.1%} (n={g['n']})"} for g in groups[:3]])
        ctx.db.add(rec)
        recs.append(r.title)
    nx = out.next_experiment
    exp = Experiment(workspace_id=ctx.workspace_id, campaign_id=camp_id, name=nx.name[:200],
                     variants=[{"label": "A", "description": nx.variant_a}, {"label": "B", "description": nx.variant_b}],
                     success_criteria=[{"metric": "saves_per_reach", "comparator": "relative_lift_gte", "target": 0.15,
                                        "variant": "B", "baseline": "A"}], status="planned", is_synthetic=synthetic,
                     learnings=f"Proposed hypothesis: {nx.hypothesis}")
    ctx.db.add(exp)
    ctx.db.flush()
    ctx.remember("next_experiment_id", exp.id)
    return ToolResult(f"{len(recs)} recommendation(s); next experiment planned: “{nx.name}”.",
                      {"recommendations": recs, "next_experiment_id": exp.id, "generator": gen.name},
                      is_mock=gen.is_mock or synthetic, tokens=tokens)


class ReportIn(ToolInput):
    campaign_id: int | None = None


@tool("generate_campaign_report", "Generate a Markdown campaign report: objectives, hypotheses, evidence, content, "
      "approvals, publishing history, observed performance, experiment results and next steps.", ReportIn,
      Permission.DRAFT)
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
