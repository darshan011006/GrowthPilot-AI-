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
from .analytics import er, latest

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


def variant_data(db: Session, exp: Experiment) -> dict[str, list[dict]]:
    items = db.execute(select(ContentItem).options(selectinload(ContentItem.metrics)).where(
        ContentItem.experiment_id == exp.id, ContentItem.status == ContentStatus.PUBLISHED)).scalars().all()
    out: dict[str, list[dict]] = {v["label"]: [] for v in exp.variants or []}
    for i in items:
        s = latest(i)
        out.setdefault(i.variant_label or "?", []).append(
            {"content_id": i.id, "engagement_rate": er(s), "source": s.source if s else None,
             "reach": s.reach if s else None})
    return out


def evaluate(db: Session, exp: Experiment) -> dict:
    data = variant_data(db, exp)
    labels = [v["label"] for v in exp.variants or []] or sorted(data)
    per = {}
    sources: set[str] = set()
    for label in labels:
        vals = [d["engagement_rate"] for d in data.get(label, []) if d["engagement_rate"] is not None]
        sources |= {d["source"] for d in data.get(label, []) if d["source"]}
        per[label] = {"n": len(vals), "mean_engagement_rate": mean(vals) if vals else None,
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
              "method": f"Difference in mean engagement rate (by reach); two-sided permutation test, "
                        f"{PERMUTATIONS} permutations, screening threshold p < {ALPHA}."}
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
        result.update({"lift": lift, "p_value": p, "challenger": challenger, "baseline": baseline})
        if lift is not None and p < ALPHA and lift >= target:
            conclusion = "supported"
            learnings = (f"Variant {challenger} was associated with {lift:+.0%} engagement rate vs {baseline} "
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
