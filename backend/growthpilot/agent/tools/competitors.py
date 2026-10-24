from __future__ import annotations

from collections import Counter, defaultdict

from pydantic import Field
from sqlalchemy import select

from ...models import Competitor, CompetitorObservation, ContentItem, EvidenceClass, ResearchFinding
from ...research.net import host_of
from ...research.web import FetchError, fetch_page, injection_signals
from ..registry import Permission, ToolBlocked, ToolContext, ToolInput, ToolResult, tool
from .common import brand

NOT_AVAILABLE = ["reach", "impressions", "saves", "audience demographics", "ad spend", "conversions", "revenue"]
NA_TEXT = "Not available through the connected source."

GAP_THEMES = {
    "Compact living": ["small-space", "small space", "compact", "layout", "dimension", "fits", "floor plan", "2bhk"],
    "Materials": ["material", "craft", "frame", "fabric", "how it's made", "wood"],
    "Styling": ["styling", "style", "inspiration", "look"],
    "Festive refresh": ["festive", "diwali", "season"],
}


class FetchCompetitorsIn(ToolInput):
    competitor_ids: list[int] = Field(default_factory=list, description="Empty = all competitors for the brand.")


def _competitors(ctx: ToolContext, ids: list[int]) -> list[Competitor]:
    b = brand(ctx)
    q = select(Competitor).where(Competitor.brand_id == b.id, Competitor.workspace_id == ctx.workspace_id)
    if ids:
        q = q.where(Competitor.id.in_(ids))
    rows = list(ctx.db.execute(q).scalars())
    if not rows:
        raise ToolBlocked("No competitors configured. Add public competitor names/URLs in Competitor Radar.",
                          blocker="no_competitors")
    return rows


@tool("fetch_competitor_data", "Collect public competitor information from permitted sources (their public website). "
      "Instagram data for other accounts is not fetched (no authorised access). Demo mode returns synthetic fixtures.",
      FetchCompetitorsIn, Permission.RESEARCH, implementation="public website fetch; fixtures in demo mode")
def fetch_competitor_data(ctx: ToolContext, inp: FetchCompetitorsIn) -> ToolResult:
    comps = _competitors(ctx, inp.competitor_ids)
    out, is_mock, errors = [], False, []
    for c in comps:
        entry = {"competitor_id": c.id, "name": c.name, "synthetic": c.is_synthetic,
                 "instagram": NA_TEXT if c.instagram_url else "No profile URL given.", "observations": 0}
        if ctx.settings.is_demo or c.is_synthetic:
            entry["observations"] = len(c.observations)
            entry["source"] = "synthetic fixture observations"
            is_mock = True
        elif c.website:
            try:
                page = fetch_page(c.website, allowed_domains=[host_of(c.website)])
                obs = CompetitorObservation(
                    workspace_id=ctx.workspace_id, competitor_id=c.id, run_id=ctx.run.id, source_type="website",
                    source_url=page.url, content_format="page", theme=(page.headings[0] if page.headings else page.title)[:160],
                    excerpt=(page.description or page.text[:200])[:240], is_synthetic=False)
                ctx.db.add(obs)
                entry["observations"] = len(c.observations) + 1
                entry["source"] = page.url
                entry["headings"] = page.headings[:10]
                entry["injection_flags"] = injection_signals(page.text)
            except FetchError as exc:
                errors.append(f"{c.name}: {exc}")
                entry["error"] = str(exc)
        else:
            entry["source"] = "No website URL given."
        out.append(entry)
    ctx.db.flush()
    summary = f"Collected data for {len(comps)} competitor(s)" + (" (synthetic fixtures)" if is_mock else "") + \
              (f"; {len(errors)} fetch error(s)" if errors else "") + ". Private metrics are not available."
    return ToolResult(summary, {"competitors": out, "not_available": {k: NA_TEXT for k in NOT_AVAILABLE},
                                "errors": errors}, is_mock=is_mock)


class AnalyseIn(ToolInput):
    competitor_ids: list[int] = Field(default_factory=list)


@tool("analyse_competitor_content", "Summarise observed competitor themes, formats, CTAs, product categories and "
      "publicly visible engagement. Reports only what was observed.", AnalyseIn, Permission.READ)
def analyse_competitor_content(ctx: ToolContext, inp: AnalyseIn) -> ToolResult:
    comps = _competitors(ctx, inp.competitor_ids)
    obs = [o for c in comps for o in c.observations]
    themes, formats, ctas, cats = Counter(), Counter(), Counter(), Counter()
    eng: dict[str, list[int]] = defaultdict(list)
    for o in obs:
        themes[o.theme] += 1
        formats[o.content_format] += 1
        if o.cta:
            ctas[o.cta] += 1
        for cat in o.product_categories or []:
            cats[cat] += 1
        if o.visible_engagement and isinstance(o.visible_engagement.get("likes"), int):
            eng[o.theme].append(o.visible_engagement["likes"])
    discount_share = sum(n for t, n in themes.items() if any(k in t for k in ("sale", "discount"))) / max(len(obs), 1)
    synthetic = bool(obs) and all(o.is_synthetic for o in obs)
    data = {
        "observations": len(obs), "themes": themes.most_common(), "formats": formats.most_common(),
        "ctas": ctas.most_common(5), "product_categories": cats.most_common(),
        "visible_likes_by_theme": {t: {"n": len(v), "mean": sum(v) / len(v)} for t, v in eng.items()},
        "discount_or_sale_share": discount_share,
        "not_available": {k: NA_TEXT for k in NOT_AVAILABLE},
        "notes": ["Visible likes are only what the source exposes; they are not reach or conversions.",
                  "Observations are a sample, not a full history."],
        "synthetic": synthetic,
    }
    top = ", ".join(f"{t} ({n})" for t, n in themes.most_common(3))
    return ToolResult(f"{len(obs)} observation(s). Top themes: {top or 'none'}. Sale/discount share: "
                      f"{discount_share:.0%}." + (" Synthetic fixtures." if synthetic else ""), data, is_mock=synthetic)


class GapsIn(ToolInput):
    pass


@tool("identify_content_gaps", "Compare trend signals with competitor themes and the brand's own past content to "
      "find under-served topics. Each gap is recorded as an inference with its supporting evidence.",
      GapsIn, Permission.DRAFT)
def identify_content_gaps(ctx: ToolContext, inp: GapsIn) -> ToolResult:
    b = brand(ctx)
    obs = ctx.db.execute(select(CompetitorObservation).join(Competitor).where(Competitor.brand_id == b.id)).scalars().all()
    trend_ids = ctx.state.get("finding_ids", [])
    trends = ctx.db.execute(select(ResearchFinding).where(ResearchFinding.id.in_(trend_ids))).scalars().all() if trend_ids else []
    own = ctx.db.execute(select(ContentItem).where(ContentItem.brand_id == b.id)).scalars().all()
    gaps = []
    for theme, keys in GAP_THEMES.items():
        support = [t for t in trends if t.topic.lower() == theme.lower()
                   or any(k in (t.statement or "").lower() for k in keys)]
        if not support:
            continue
        comp_cov = [o for o in obs if any(k in f"{o.theme} {o.excerpt}".lower() for k in keys)]
        own_cov = [i for i in own if any(k in f"{i.pillar} {i.caption}".lower() for k in keys)]
        if len(comp_cov) <= 1:
            synthetic = all(t.is_synthetic for t in support) or all(o.is_synthetic for o in obs)
            statement = (f"Gap: “{theme}” is supported by {len(support)} signal(s) but appears in only "
                         f"{len(comp_cov)} of {len(obs)} observed competitor posts; the brand has {len(own_cov)} past "
                         "post(s) on it.")
            f = ResearchFinding(workspace_id=ctx.workspace_id, brand_id=b.id, run_id=ctx.run.id, topic=theme,
                                statement=statement, classification=EvidenceClass.INFERENCE, source_type="analysis",
                                source_title="GrowthPilot gap analysis", is_synthetic=synthetic,
                                evidence_excerpt="Based on findings " + ", ".join(f"#{t.id}" for t in support))
            ctx.db.add(f)
            ctx.db.flush()
            gaps.append({"theme": theme, "finding_id": f.id, "evidence_ids": [t.id for t in support] + [f.id],
                         "competitor_coverage": len(comp_cov), "own_coverage": len(own_cov), "statement": statement,
                         "classification": "inference"})
    ctx.remember("gaps", gaps)
    ctx.remember_ids("finding_ids", [g["finding_id"] for g in gaps])
    if not gaps:
        return ToolResult("No clear gaps: every supported theme is already covered by competitors.", {"gaps": []})
    return ToolResult(f"{len(gaps)} gap(s): " + "; ".join(f"{g['theme']} (competitor coverage {g['competitor_coverage']})"
                                                          for g in gaps), {"gaps": gaps},
                      is_mock=all(ctx.db.get(ResearchFinding, g["finding_id"]).is_synthetic for g in gaps))
