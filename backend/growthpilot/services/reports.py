"""Campaign reports as Markdown (viewable in the app and downloadable)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Campaign,
    ContentItem,
    Experiment,
    Hypothesis,
    PublishAttempt,
    Recommendation,
    Report,
    ResearchFinding,
    User,
    utcnow,
)
from .analytics import METRIC_DEFINITIONS, summary

SOURCE_LABEL = {"synthetic": "SYNTHETIC demo data", "real": "real connected-account data", "mixed":
                "MIXED real and synthetic data", "none": "no performance data yet"}


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.1%}"


def _md(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def build(db: Session, campaign: Campaign, run_id: str | None = None) -> Report:
    ws = campaign.workspace_id
    items = db.execute(select(ContentItem).where(ContentItem.campaign_id == campaign.id)
                       .order_by(ContentItem.planned_at)).scalars().all()
    hyps = db.execute(select(Hypothesis).where(Hypothesis.campaign_id == campaign.id)
                      .order_by(Hypothesis.rank)).scalars().all()
    exps = db.execute(select(Experiment).where(Experiment.campaign_id == campaign.id)).scalars().all()
    recs = db.execute(select(Recommendation).where(Recommendation.campaign_id == campaign.id)).scalars().all()
    ev_ids = sorted({i for h in hyps for i in (h.evidence_ids or [])})
    evidence = db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(ev_ids),
                                                        ResearchFinding.workspace_id == ws)).scalars().all() if ev_ids else []
    users = {u.id: u.name for u in db.execute(select(User)).scalars()}
    stats = summary(db, ws, campaign.id)
    synthetic = campaign.is_synthetic or stats["data_source"] in ("synthetic", "mixed")

    L: list[str] = [f"# Campaign report: {campaign.name}", ""]
    L.append(f"_Generated {utcnow():%Y-%m-%d %H:%M} UTC. Performance source: {SOURCE_LABEL[stats['data_source']]}._")
    if synthetic:
        L += ["", "> **Demo data notice:** parts of this report use synthetic data or fictional fixtures. They "
                  "demonstrate the workflow and are not evidence about real customers."]
    L += ["", "## Objective", campaign.objective or "—", "",
          f"- **Audience:** {campaign.audience or '—'}", f"- **Geography / language:** {campaign.geography or '—'} / "
          f"{campaign.language}", f"- **Period:** {campaign.start_date or '—'} → {campaign.end_date or '—'}",
          f"- **Platforms:** {', '.join(campaign.platforms or []) or '—'}",
          f"- **Pillars:** {', '.join(campaign.pillars or []) or '—'}", ""]
    if campaign.success_criteria:
        L.append("**Success criteria:** " + "; ".join(
            f"{c.get('metric')} {c.get('comparator')} {c.get('target')}" for c in campaign.success_criteria))
        L.append("")
    L += ["## Hypotheses", ""]
    if hyps:
        L += ["| Rank | Hypothesis | Score* | Status |", "|---|---|---|---|"]
        for h in hyps:
            L.append(f"| {h.rank} | {_md(h.statement)} | {h.total_score:.1f} | {h.status}{' ✓ selected' if h.selected else ''} |")
        L += ["", "_*Heuristic ranking score from stated criteria; not a probability._", ""]
    else:
        L += ["No hypotheses recorded.", ""]
    L += ["## Research evidence", ""]
    if evidence:
        for e in evidence:
            src = e.source_url or e.source_title or e.source_type
            L.append(f"- [{e.classification.replace('_', ' ')}] {_md(e.statement)} — _{src}_, retrieved "
                     f"{e.retrieved_at:%Y-%m-%d}{' (synthetic fixture)' if e.is_synthetic else ''}")
    else:
        L.append("No linked evidence.")
    L += ["", "## Content produced", "", "| # | When (UTC) | Type | Pillar | Variant | Status | Version | Approved by |",
          "|---|---|---|---|---|---|---|---|"]
    for i in items:
        when = i.published_at or i.scheduled_at or i.planned_at
        L.append(f"| {i.id} | {when:%Y-%m-%d %H:%M} | {i.content_type} | {_md(i.pillar)} | {i.variant_label or '—'} | "
                 f"{i.status} | v{i.version} | {users.get(i.approved_by, '—') if i.approved_by else '—'} |"
                 if when else f"| {i.id} | — | {i.content_type} | {_md(i.pillar)} | {i.variant_label or '—'} | "
                 f"{i.status} | v{i.version} | — |")
    attempts = db.execute(select(PublishAttempt).where(PublishAttempt.content_id.in_([i.id for i in items]))
                          .order_by(PublishAttempt.attempted_at)).scalars().all() if items else []
    L += ["", "## Publishing history", ""]
    if attempts:
        for a in attempts:
            L.append(f"- #{a.content_id} via {a.adapter} ({'LIVE' if a.live else 'simulated'}): "
                     f"{'success' if a.success else 'failed'} {a.attempted_at:%Y-%m-%d %H:%M} — "
                     f"{_md(a.summary or a.error or '')}")
    else:
        L.append("Nothing has been published yet.")
    t = stats["totals"]
    L += ["", "## Observed performance", "",
          f"Posts with metrics: {stats['with_metrics']} of {stats['published']} published. "
          f"Data freshness: {stats['freshness'] or 'n/a'}.", "",
          f"- Reach: {t.get('reach', 0):,}", f"- Interactions: {t.get('interactions', 0):,}",
          f"- Engagement rate by reach: {_pct(t.get('engagement_rate_by_reach'))}", ""]
    if stats["by_content_type"]:
        L += ["| Content type | Posts | Mean engagement rate |", "|---|---|---|"]
        L += [f"| {g['key']} | {g['n']} | {_pct(g['mean_engagement_rate'])} |" for g in stats["by_content_type"]]
        L.append("")
    L.append(f"_Definition — engagement rate by reach: {METRIC_DEFINITIONS['engagement_rate_by_reach']['definition']}_")
    L += ["", "## Experiments", ""]
    for e in exps:
        L.append(f"### {e.name}")
        L.append(f"- Status: {e.status}; conclusion: **{e.conclusion or 'not evaluated'}**; data: {e.data_source or '—'}")
        if e.result and e.result.get("per_variant"):
            for label, v in e.result["per_variant"].items():
                L.append(f"- Variant {label}: n={v['n']}, mean ER {_pct(v['mean_engagement_rate'])}")
            if e.result.get("p_value") is not None:
                L.append(f"- Lift {e.result.get('lift', 0):+.0%}, permutation p≈{e.result['p_value']:.3f} "
                         f"({e.result.get('method', '')})")
        if e.learnings:
            L.append(f"- What we learned: {e.learnings}")
        L.append("")
    if not exps:
        L += ["No experiments.", ""]
    L += ["## What worked and what's uncertain", ""]
    supported = [e for e in exps if e.conclusion == "supported"]
    unclear = [e for e in exps if e.conclusion in ("inconclusive", "")]
    L.append("- Worked (association, not proof): " + ("; ".join(e.name for e in supported) if supported else "nothing "
             "clearly yet."))
    L.append("- Uncertain: " + ("; ".join(e.name for e in unclear) if unclear else "see limitations below."))
    L.append("- Limitations: small samples, posts differ in timing and creative, platform metrics are estimates.")
    L += ["", "## Recommended next steps", ""]
    L += [f"- **{r.title}** ({r.priority}) — {r.detail} _Uncertainty: {r.uncertainty or 'n/a'}_" for r in recs] or [
        "- Run the evaluation workflow after posts have metrics."]
    md = "\n".join(L) + "\n"
    rep = Report(workspace_id=ws, campaign_id=campaign.id, run_id=run_id, title=f"Report — {campaign.name}",
                 markdown=md, data_source=stats["data_source"])
    db.add(rep)
    db.flush()
    return rep
