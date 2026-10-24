"""Performance metrics: collection, definitions and aggregation."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..adapters import AdapterError, get_adapter
from ..models import Campaign, ContentItem, ContentStatus, MetricSnapshot, utcnow
from .connections import context

log = logging.getLogger(__name__)

METRIC_DEFINITIONS = {
    "reach": {"label": "Reach", "kind": "raw", "definition": "Unique accounts that saw the post (Instagram "
              "reports this as an estimate)."},
    "views": {"label": "Views", "kind": "raw", "definition": "Times the post was displayed/played, as reported."},
    "likes": {"label": "Likes", "kind": "raw", "definition": "Likes on the post."},
    "comments": {"label": "Comments", "kind": "raw", "definition": "Comments on the post."},
    "shares": {"label": "Shares", "kind": "raw", "definition": "Times the post was shared."},
    "saves": {"label": "Saves", "kind": "raw", "definition": "Times the post was saved."},
    "interactions": {"label": "Interactions", "kind": "derived",
                     "definition": "likes + comments + shares + saves (only counted when all four are available)."},
    "engagement_rate_by_reach": {"label": "Engagement rate (by reach)", "kind": "derived",
                                 "definition": "interactions ÷ reach. Not comparable with platforms that report "
                                               "impressions instead of reach."},
}

TRACK_FOR = timedelta(days=45)
REFRESH_EVERY = timedelta(hours=3)


def latest(item: ContentItem) -> MetricSnapshot | None:
    return item.metrics[-1] if item.metrics else None


def interactions(s: MetricSnapshot | None) -> int | None:
    if s is None or None in (s.likes, s.comments, s.shares, s.saves):
        return None
    return s.likes + s.comments + s.shares + s.saves


def er(s: MetricSnapshot | None) -> float | None:
    i = interactions(s)
    if i is None or not s.reach:
        return None
    return i / s.reach


def collect(db: Session, workspace_id: int, *, item_ids: list[int] | None = None, force: bool = False) -> dict:
    """Pull metrics from adapters for recently published items."""
    now = utcnow()
    q = select(ContentItem).options(selectinload(ContentItem.metrics), selectinload(ContentItem.connection)).where(
        ContentItem.workspace_id == workspace_id, ContentItem.status == ContentStatus.PUBLISHED,
        ContentItem.published_at >= now - TRACK_FOR)
    if item_ids:
        q = q.where(ContentItem.id.in_(item_ids))
    stats = {"collected": 0, "unavailable": 0, "errors": [], "sources": set()}
    for item in db.execute(q).scalars().all():
        last = latest(item)
        if not force and last and now - last.captured_at < REFRESH_EVERY:
            continue
        if not item.connection or not item.external_id:
            stats["unavailable"] += 1
            continue
        try:
            adapter = get_adapter(item.connection.adapter)
            m = adapter.fetch_metrics(context(db, item.connection), item.external_id,
                                      hours_since=(now - item.published_at).total_seconds() / 3600,
                                      hints={"content_type": item.content_type, "pillar": item.pillar})
        except AdapterError as exc:
            stats["errors"].append(f"#{item.id}: {exc}")
            continue
        if m is None:
            stats["unavailable"] += 1
            continue
        source = "instagram_api" if adapter.external else "synthetic"
        stats["sources"].add(source)
        db.add(MetricSnapshot(content_id=item.id, reach=m.reach, views=m.views, likes=m.likes, comments=m.comments,
                              shares=m.shares, saves=m.saves, profile_visits=m.profile_visits,
                              link_clicks=m.link_clicks, source=source, raw=m.raw))
        stats["collected"] += 1
    db.commit()
    stats["sources"] = sorted(stats["sources"])
    return stats


def _data_source(sources: set[str]) -> str:
    if not sources:
        return "none"
    if sources == {"synthetic"}:
        return "synthetic"
    if "synthetic" in sources:
        return "mixed"
    return "real"


def item_rows(db: Session, workspace_id: int, campaign_id: int | None = None) -> list[dict]:
    q = select(ContentItem).options(selectinload(ContentItem.metrics)).where(
        ContentItem.workspace_id == workspace_id, ContentItem.status == ContentStatus.PUBLISHED)
    if campaign_id:
        q = q.where(ContentItem.campaign_id == campaign_id)
    rows = []
    for item in db.execute(q).scalars().all():
        s = latest(item)
        rows.append({
            "id": item.id, "title": item.title or item.caption[:60], "platform": item.platform,
            "content_type": item.content_type, "pillar": item.pillar or "unspecified",
            "campaign_id": item.campaign_id, "variant": item.variant_label, "experiment_id": item.experiment_id,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "has_metrics": s is not None, "source": s.source if s else None,
            "captured_at": s.captured_at.isoformat() if s else None,
            "reach": s.reach if s else None, "views": s.views if s else None, "likes": s.likes if s else None,
            "comments": s.comments if s else None, "shares": s.shares if s else None,
            "saves": s.saves if s else None, "interactions": interactions(s), "engagement_rate": er(s),
        })
    return rows


def group(rows: list[dict], key: str) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["engagement_rate"] is not None:
            buckets[str(r[key] or "—")].append(r)
    out = []
    for k, rs in buckets.items():
        ers = [r["engagement_rate"] for r in rs]
        out.append({"key": k, "n": len(rs), "mean_engagement_rate": mean(ers), "min": min(ers), "max": max(ers),
                    "reach": sum(r["reach"] or 0 for r in rs), "interactions": sum(r["interactions"] or 0 for r in rs)})
    return sorted(out, key=lambda g: g["mean_engagement_rate"], reverse=True)


def summary(db: Session, workspace_id: int, campaign_id: int | None = None) -> dict:
    rows = item_rows(db, workspace_id, campaign_id)
    with_m = [r for r in rows if r["has_metrics"]]
    sources = {r["source"] for r in with_m if r["source"]}
    totals = {k: sum(r[k] or 0 for r in with_m) for k in ("reach", "views", "likes", "comments", "shares", "saves")}
    inter = [r["interactions"] for r in with_m if r["interactions"] is not None]
    reach_for_er = sum(r["reach"] or 0 for r in with_m if r["interactions"] is not None)
    totals["interactions"] = sum(inter)
    totals["engagement_rate_by_reach"] = (sum(inter) / reach_for_er) if reach_for_er else None
    daily: dict[str, dict] = defaultdict(lambda: {"reach": 0, "interactions": 0, "posts": 0})
    for r in with_m:
        if r["published_at"]:
            d = daily[r["published_at"][:10]]
            d["reach"] += r["reach"] or 0
            d["interactions"] += r["interactions"] or 0
            d["posts"] += 1
    campaigns = {c.id: c.name for c in db.execute(select(Campaign).where(Campaign.workspace_id == workspace_id)).scalars()}
    by_campaign = group([dict(r, campaign_name=campaigns.get(r["campaign_id"], "No campaign")) for r in with_m],
                        "campaign_name")
    freshness = max((r["captured_at"] for r in with_m if r["captured_at"]), default=None)
    return {
        "data_source": _data_source(sources),
        "freshness": freshness,
        "published": len(rows),
        "with_metrics": len(with_m),
        "missing_metrics": len(rows) - len(with_m),
        "totals": totals,
        "by_content_type": group(with_m, "content_type"),
        "by_pillar": group(with_m, "pillar"),
        "by_platform": group(with_m, "platform"),
        "by_campaign": by_campaign,
        "daily": [{"date": k, **v} for k, v in sorted(daily.items())],
        "items": sorted(with_m, key=lambda r: r["engagement_rate"] or 0, reverse=True),
        "definitions": METRIC_DEFINITIONS,
    }
