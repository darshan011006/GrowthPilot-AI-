"""Experiment evaluation with explicit sample-size and uncertainty handling.

Conclusions use association language only. With small samples the honest answer is usually
"inconclusive", and the evaluator says what to measure next.
"""

from __future__ import annotations

import random
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import ContentItem, ContentStatus, Experiment, Hypothesis, utcnow
from .analytics import METRIC_DEFINITIONS, latest, metric_value

PERMUTATIONS = 4000
ALPHA = 0.10  # deliberately lenient screening threshold, stated in every result


def _perm_p(a: list[float], b: list[float], seed: int) -> float:
    """Two-sided permutation test on difference in means (deterministic seed)."""
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    observed = abs(mean(a) - mean(b))
    pooled = a + b
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(pooled)
        if abs(mean(pooled[: len(a)]) - mean(pooled[len(a):])) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def experiment_platform(exp: Experiment) -> str | None:
    """A/B comparisons run within one platform so channel differences don't masquerade as effects."""
    return (exp.result or {}).get("platform") or (exp.baseline or {}).get("filters", {}).get("platform") or None


def variant_data(db: Session, exp: Experiment, platform: str | None = "auto") -> dict[str, list[dict]]:
    items = db.execute(select(ContentItem).options(selectinload(ContentItem.metrics)).where(
        ContentItem.experiment_id == exp.id, ContentItem.status == ContentStatus.PUBLISHED)).scalars().all()
    if platform == "auto":
        platform = experiment_platform(exp)
        if platform is None:
            plats = {i.platform for i in items}
            platform = "instagram" if "instagram" in plats else (next(iter(plats)) if len(plats) == 1 else None)
    if platform:
        items = [i for i in items if i.platform == platform]
    out: dict[str, list[dict]] = {v["label"]: [] for v in exp.variants or []}
    for i in items:
        s = latest(i)
        out.setdefault(i.variant_label or "?", []).append(
            {"content_id": i.id, "engagement_rate": metric_value(s, exp.primary_metric), "source": s.source if s else None,
             "reach": s.reach if s else None, "platform": i.platform})
    return out


def confidence(p: float | None, n_min: int, data_source: str) -> str:
    if p is None:
        return "none"
    if p < 0.05 and n_min >= 8:
        level = "high"
    elif p < ALPHA and n_min >= 3:
        level = "medium"
    else:
        level = "low"
    return level


def evaluate(db: Session, exp: Experiment) -> dict:
    data = variant_data(db, exp)
    platforms = sorted({d.get("platform") for rows in data.values() for d in rows if d.get("platform")})
    metric_label = METRIC_DEFINITIONS.get(exp.primary_metric, {}).get("label", exp.primary_metric).lower()
    labels = [v["label"] for v in exp.variants or []] or sorted(data)
    per = {}
    sources: set[str] = set()
    for label in labels:
        vals = [d["engagement_rate"] for d in data.get(label, []) if d["engagement_rate"] is not None]
        sources |= {d["source"] for d in data.get(label, []) if d["source"]}
        per[label] = {"n": len(vals), "mean_engagement_rate": mean(vals) if vals else None,
                      "mean": mean(vals) if vals else None,
                      "posts": [d["content_id"] for d in data.get(label, [])],
                      "missing_metrics": sum(1 for d in data.get(label, []) if d["engagement_rate"] is None)}
    crit = (exp.success_criteria or [{}])[0]
    target = float(crit.get("target", 0.15))
    challenger = crit.get("variant") or (labels[1] if len(labels) > 1 else None)
    baseline = crit.get("baseline") or (labels[0] if labels else None)
    data_source = "none" if not sources else ("synthetic" if sources == {"synthetic"} else
                                              "mixed" if "synthetic" in sources else "real")
    result = {"per_variant": per, "criterion": crit or {"metric": exp.primary_metric, "comparator": "relative_lift_gte",
                                                        "target": target}, "alpha": ALPHA, "data_source": data_source,
              "platform": platforms[0] if len(platforms) == 1 else None, "metric": exp.primary_metric,
              "method": f"Difference in mean {metric_label} between variants"
                        + (f" on {platforms[0]} only" if len(platforms) == 1 else "")
                        + f"; two-sided permutation test, {PERMUTATIONS} permutations, screening threshold p < {ALPHA}."}
    exp.comparison_method = result["method"]
    small = [label for label in labels if per[label]["n"] < exp.min_sample_per_variant]
    if not labels:
        small = ["(no variants)"]
    if not challenger or not baseline or small:
        conclusion = "inconclusive"
        need = ", ".join(f"{label} has {per[label]['n']}" for label in small if label in per) or "variants not defined"
        learnings = (f"Not enough data to evaluate: need at least {exp.min_sample_per_variant} posts with metrics per "
                     f"variant ({need}).")
        nxt = "Keep the experiment running and publish more posts in each variant before drawing conclusions."
    else:
        a = [d["engagement_rate"] for d in data[baseline] if d["engagement_rate"] is not None]
        b = [d["engagement_rate"] for d in data[challenger] if d["engagement_rate"] is not None]
        lift = (mean(b) - mean(a)) / mean(a) if mean(a) else None
        p = _perm_p(a, b, seed=exp.id or 0)
        result.update({"lift": lift, "p_value": p, "challenger": challenger, "baseline": baseline,
                       "confidence": confidence(p, min(len(a), len(b)), data_source)})
        base = exp.baseline or {}
        if base.get("value"):
            result["vs_historical_baseline"] = {
                "baseline_value": base["value"], "baseline_n": base.get("n"), "challenger_mean": mean(b),
                "lift": (mean(b) - base["value"]) / base["value"], "note": base.get("note", "")}
        if lift is not None and p < ALPHA and lift >= target:
            conclusion = "supported"
            learnings = (f"Variant {challenger} was associated with {lift:+.0%} {metric_label} vs {baseline} "
                         f"(p≈{p:.3f}, n={len(b)} vs {len(a)}). This is an association in a small sample, not proof "
                         "of cause; audience, timing and creative quality also differ between posts.")
            nxt = f"Shift more of next week's posts toward variant {challenger}'s approach and keep a smaller " \
                  f"{baseline} control to check the effect holds."
        elif lift is not None and p < ALPHA and lift < 0:
            conclusion = "not_supported"
            learnings = (f"Variant {challenger} underperformed {baseline} ({lift:+.0%}, p≈{p:.3f}). The hypothesis is "
                         "not supported in this sample.")
            nxt = f"Revert to {baseline}'s approach and test a different hypothesis."
        else:
            conclusion = "inconclusive"
            learnings = (f"Observed lift {lift:+.0%} (p≈{p:.3f}) doesn't clear the success criterion "
                         f"(≥{target:.0%} with p < {ALPHA}). The difference may be noise." if lift is not None else
                         "Baseline engagement is zero; can't compute a lift.")
            nxt = "Run another cycle with more posts per variant, or test a bolder variation."
    if data_source == "synthetic":
        learnings += " Based on SYNTHETIC demo metrics — not evidence about real customers."
    if "vs_historical_baseline" in result:
        hb = result["vs_historical_baseline"]
        learnings += (f" Against the brand's earlier posts ({hb['baseline_n']} post(s)), variant {challenger} is "
                      f"{hb['lift']:+.0%}.")
    exp.confidence = result.get("confidence", "none") if conclusion != "inconclusive" or "p_value" in result else "none"
    exp.result = result
    exp.conclusion = conclusion
    exp.learnings = learnings
    exp.next_recommendation = nxt
    exp.data_source = data_source
    # Keep collecting when the only problem is sample size; otherwise the experiment is closed.
    exp.status = "running" if (small and exp.status in ("running", "planned")) else "evaluated"
    exp.evaluated_at = utcnow()
    if exp.hypothesis_id:
        h = db.get(Hypothesis, exp.hypothesis_id)
        if h:
            h.status = {"supported": "supported", "not_supported": "refuted"}.get(conclusion, "inconclusive")
    return result | {"conclusion": conclusion, "learnings": learnings, "next_recommendation": nxt}
