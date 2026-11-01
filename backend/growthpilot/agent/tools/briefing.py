"""create_content_brief, database side: gather each post's facts, plan the weekly mix, write the briefs.

The rules themselves live in ``agent.briefs`` (pure, unit-tested). Nothing here renders, calls Canva or publishes.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ...catalogue import freshness, usable_for_brand, usable_products
from ...models import (
    Asset,
    Campaign,
    Competitor,
    CompetitorObservation,
    ContentItem,
    ContentStatus,
    Product,
    ResearchFinding,
    Workspace,
)
from ...platforms import SPECS
from ...services import festival_dates, seasonal
from ...services.validation import check_product_claims
from .. import briefs as B
from ..generation import pillar_kind
from ..registry import ToolContext
from .common import brand, promotable

LAYOUT_CODES = {"layout", "text_fit", "safe_margin", "glyphs"}
CLAIM_CODES = {"price", "price_freshness", "mrp", "offer", "availability", "warranty", "certification",
               "health_claim", "superlative", "material", "dimension", "restricted", "prohibited", "on_image_text",
               "listing"}
TREND_TYPES = {"web_search", "website", "fixture", "analysis", "competitor"}


def product_facts(p: Product) -> B.ProductFacts:
    ok, _ = promotable(p)
    codes = {q.get("code") for q in p.data_quality or []}
    price_ok = (p.price is not None and freshness(p)["state"] == "fresh"
                and not codes & {"price_suspicious", "no_price"})
    trust = {"product_photo": "real_match", "stock_photo": "stock", "unverified": "unknown",
             "none": "none"}.get(p.image_kind or "", "unknown")
    if trust == "none" and p.image_asset_id:
        trust = "unknown"  # a photo is attached but nothing says where it came from
    return B.ProductFacts(sku=p.sku, name=p.name, category=p.category or "", description=p.description or "",
                          materials=list(p.materials or [])[:3], dimensions=p.dimensions or "", price=p.price,
                          mrp=p.mrp, stock=p.stock, price_ok=price_ok, promotable=ok,
                          religious=bool(B.religious_terms(f"{p.name} {p.category}")), trust=trust,
                          photo_asset_id=p.image_asset_id)


def image_options(ctx: ToolContext, item: ContentItem, pf: B.ProductFacts | None) -> tuple[list[B.ImageOption],
                                                                                           list[dict]]:
    """Images a post may use: team uploads linked to it, and the product's real store photo."""
    opts, issues = [], []
    for aid in ([item.asset_id] if item.asset_id else []) + list(item.slide_asset_ids or []):
        a = ctx.db.get(Asset, aid)
        if a and a.workspace_id == ctx.workspace_id and a.source == "upload":
            opts.append(B.ImageOption("uploaded", a.id, "uploaded"))
    if pf and not pf.religious:
        if pf.trust == "real_match" and pf.photo_asset_id:
            opts.append(B.ImageOption("brand_site", pf.photo_asset_id, "real_match", pf.sku))
        elif pf.trust == "real_match":
            issues.append({"code": "photo_not_downloaded", "message": f"{pf.name}: the store lists a real photo but "
                           "it hasn't been downloaded into the asset library (sync the catalogue)."})
        elif pf.trust == "unknown" and pf.photo_asset_id:
            opts.append(B.ImageOption("brand_site", pf.photo_asset_id, "unknown", pf.sku))
        elif pf.trust == "stock":
            issues.append({"code": "stock_photo_only", "message": f"{pf.name}: the store only lists a generic stock "
                           "image, which is never shown as the product."})
        elif not opts:
            issues.append({"code": "no_product_photo", "message": f"{pf.name}: no photo of the product is available."})
    return opts, issues


def capability(opts: list[B.ImageOption]) -> str:
    if any(o.trust in ("real_match", "uploaded") for o in opts):
        return "trusted"
    return "unknown" if opts else "none"


def festival_calendar(ctx: ToolContext, today: date) -> tuple[list[dict], list[str], list[dict]]:
    """Verified festivals, names with no verified upcoming date, and unverified calendar hints.

    A date comes from the brand's own calendar if it has one, else from the checked official lists in
    ``services.festival_dates``. The built-in seasonal calendar is only ever a hint."""
    b = brand(ctx)
    src = b.catalogue_source or {}
    verified, undated = [], []
    for x in src.get("festivals") or []:
        name = str(x.get("name", ""))[:80]
        start = B.parse_day(x.get("date") or x.get("startDate") or x.get("start"))
        end = B.parse_day(x.get("endDate") or x.get("end")) or start
        if start:
            verified.append({"name": name, "start": start, "end": end,
                             "source": f"{b.name} festival calendar ({src.get('label') or src.get('kind') or 'brand'})"})
            continue
        occ = festival_dates.next_verified(x.get("slug") or name, today)
        if occ:
            verified.append({"name": name, "start": occ["start"], "end": occ["end"],
                             "source": f"{occ['source']} (checked {festival_dates.CHECKED})"[:300]})
        elif name:
            undated.append(name)
    hints = [{"name": o["name"], "hint": f"{o['start']:%d %b %Y}", "start": o["start"], "end": o["end"]}
             for o in seasonal.upcoming(today, within_days=B.FESTIVAL_WINDOW_DAYS + 14) if o["kind"] == "festival"]
    return verified, undated, hints


def recent_posts(ctx: ToolContext, brand_id: int, exclude: set[int], window: int) -> list[B.RecentPost]:
    rows = ctx.db.execute(
        select(ContentItem).where(ContentItem.brand_id == brand_id, ContentItem.master_id.is_(None),
                                  ContentItem.id.notin_(exclude or {0}),
                                  ContentItem.status != ContentStatus.CANCELLED)
        .order_by(func.coalesce(ContentItem.planned_at, ContentItem.created_at).desc()).limit(window)).scalars()
    out = []
    for i in rows:
        cb = i.creative_brief or {}
        st = cb.get("style") or {}
        out.append(B.RecentPost(headline=cb.get("headline") or i.hook or "", tagline=cb.get("tagline") or "",
                                angle=cb.get("angle"), layout=st.get("layout"), palette=st.get("palette")))
    return out


def qa_feedback(ctx: ToolContext, item: ContentItem, brand_render_fails: set[str]) -> B.QA:
    """Turn earlier validation failures, render checks and review notes into brief adjustments."""
    qa = B.QA()
    fails = [c for sec in ("product_claims", "brand", "platform") for c in (item.validation or {}).get(sec, [])
             if c.get("status") == "fail"]
    state = ctx.state.get("validation_failures", {})
    for k in (f"product_claims:{item.id}", f"brand:{item.id}", f"creative:{item.id}"):
        fails += [f for f in state.get(k, []) if isinstance(f, dict)]
    for aid in ([item.asset_id] if item.asset_id else []) + list(item.slide_asset_ids or []):
        a = ctx.db.get(Asset, aid)
        if a and a.source == "rendered":
            fails += [c for c in (a.meta or {}).get("checks", []) if c.get("status") == "fail"]
    codes = {str(c.get("code", "")) for c in fails} | brand_render_fails
    if codes & LAYOUT_CODES:
        qa.short_headline = qa.simple_layout = True
        qa.notes.append("earlier posters had text overlap or overflow, so a shorter headline and a simpler layout")
    if "contrast" in codes:
        qa.high_contrast = True
        qa.notes.append("earlier contrast failure, so a high-contrast palette")
    if codes & CLAIM_CODES:
        qa.drop_price = True
        qa.notes.append("earlier claim failures, so no price claim")
    if (item.review_note or "").strip():
        qa.notes.append("reviewer note on this post was taken into account")
    return qa


def _local_date(dt: datetime | None, tz: ZoneInfo, fallback: date) -> date:
    if dt is None:
        return fallback
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).date()


def _relevant_findings(findings: list[ResearchFinding], keys: list[str]) -> list[int]:
    keys = [k.lower() for k in keys if k and len(k) > 3]
    scored = []
    for f in findings:
        text = f"{f.topic} {f.statement}".lower()
        hits = sum(1 for k in keys if k in text)
        if hits:
            scored.append((-hits, f.id))
    return [i for _, i in sorted(scored)[:3]]


def write_briefs(ctx: ToolContext, rows: list[ContentItem], gen, repeat_window: int | None, apply) -> dict:
    """Plan the mix and write one validated brief per post. ``apply`` saves fields as a new content version."""
    b = brand(ctx)
    ws = ctx.db.get(Workspace, ctx.workspace_id)
    tz = ZoneInfo(ws.timezone or "UTC")
    today = datetime.now(tz).date()
    window = repeat_window or int((b.posting_constraints or {}).get("brief_repeat_window") or B.DEFAULT_REPEAT_WINDOW)
    params = ctx.state.get("params", {})
    camp = ctx.db.get(Campaign, ctx.state.get("campaign_id") or 0)
    run_issues: list[dict] = []

    videos = [i for i in rows if i.content_type in ("reel", "story", "video")]
    if videos:
        run_issues.append({"code": "video_not_briefed", "message": f"{len(videos)} video item(s) skipped: briefs "
                           "cover single images and carousels."})
    rows = [i for i in rows if i not in videos]

    verified, undated, hints = festival_calendar(ctx, today)
    if undated:
        run_issues.append({"code": "festival_date_missing", "message": "No verified upcoming date for "
                           f"{', '.join(undated)}; posts about them stay evergreen until a checked date is added "
                           "(services/festival_dates.py or the brand's festival calendar)."})
    for h in hints:
        if festival_dates.festival_key(h["name"]) not in {festival_dates.festival_key(v["name"]) for v in verified}:
            run_issues.append({"code": "festival_unverified", "message": f"{h['name']}: GrowthPilot's built-in "
                               f"planning calendar lists {h['hint']} but marks it “confirm locally”, so it wasn't used."})

    comp_rows = ctx.db.execute(select(CompetitorObservation).join(Competitor).where(
        Competitor.brand_id == b.id).order_by(CompetitorObservation.observed_at.desc())).scalars().all()
    comp_names = [c.name for c in ctx.db.execute(select(Competitor).where(Competitor.brand_id == b.id)).scalars()]
    if not comp_rows:
        run_issues.append({"code": "no_competitor_data", "message": "No competitor references; briefs use no "
                           "competitor patterns."})
    fids = ctx.state.get("finding_ids", [])
    findings = [f for f in ctx.db.execute(select(ResearchFinding).where(
        ResearchFinding.id.in_(fids or [0]), ResearchFinding.workspace_id == ctx.workspace_id)).scalars()
        if f.source_type in TREND_TYPES]
    if not findings:
        run_issues.append({"code": "no_trend_signals", "message": "No research findings in this run to cite."})
    groups = {g["key"]: g for g in ctx.state.get("compare_pillar") or []}
    if not groups:
        run_issues.append({"code": "no_analytics", "message": "No past performance by pillar to learn from."})

    render_fails: set[str] = set()
    for a in ctx.db.execute(select(Asset).where(Asset.brand_id == b.id, Asset.source == "rendered")
                            .order_by(Asset.created_at.desc()).limit(12)).scalars():
        render_fails |= {str(c.get("code")) for c in (a.meta or {}).get("checks", []) if c.get("status") == "fail"
                         and c.get("code") in LAYOUT_CODES | {"contrast"}}

    # Products: swap out deity/idol products, and give image slots a real photo where the run has one.
    pool_ids = list(ctx.state.get("product_ids", []))
    pool = {p.id: p for p in usable_products(ctx.db, b, pool_ids)}
    prod_of: dict[int, Product | None] = {}
    for i in rows:
        pid = (i.product_ids or [None])[0]
        p = ctx.db.get(Product, pid) if pid else None
        prod_of[i.id] = p if usable_for_brand(b, p) else None
    used = {p.id for p in prod_of.values() if p}
    swaps: dict[int, str] = {}

    def candidates(need_photo: bool) -> list[Product]:
        out = []
        for pid in pool_ids:
            p = pool.get(pid)
            if p is None or p.id in used or not promotable(p)[0]:
                continue
            pf = product_facts(p)
            if pf.religious or (need_photo and not (pf.trust == "real_match" and pf.photo_asset_id)):
                continue
            out.append(p)
        return out

    for i in rows:
        p = prod_of[i.id]
        if p is not None and product_facts(p).religious:
            alt = next(iter(candidates(False)), None)
            if alt is not None:
                prod_of[i.id], swaps[i.id] = alt, f"{p.name} shows a deity or idol, so {alt.name} is featured instead"
                used.add(alt.id)

    facts_img = {i.id: image_options(ctx, i, product_facts(prod_of[i.id]) if prod_of[i.id] else None) for i in rows}
    slots = [(i.id, i.content_type, capability(facts_img[i.id][0])) for i in rows]
    need = sum(1 for k in range(len(rows)) if B.MIX_PATTERN[k % len(B.MIX_PATTERN)] != "text_only")
    have = sum(1 for s in slots if s[2] != "none")
    if have < need:
        for i in sorted(rows, key=lambda r: (r.content_type == "carousel", r.id)):
            if have >= need:
                break
            if capability(facts_img[i.id][0]) != "none" or pillar_kind(i.pillar) == "know_how":
                continue
            alt = next(iter(candidates(True)), None)
            if alt is None:
                break
            old = prod_of[i.id]
            prod_of[i.id], swaps[i.id] = alt, (f"{alt.name} has a real store photo" +
                                               (f"; replaces {old.name}" if old else ""))
            used.add(alt.id)
            facts_img[i.id] = image_options(ctx, i, product_facts(alt))
            have += 1
        slots = [(i.id, i.content_type, capability(facts_img[i.id][0])) for i in rows]
    roles, notes = B.plan_mix(slots)
    run_issues += [{"code": "mix_shortfall", "message": n} for n in notes]

    batch_ids = {i.id for i in rows}
    older = recent_posts(ctx, b.id, batch_ids, window)
    done_recent: list[B.RecentPost] = []
    categories = [c for c, in ctx.db.execute(select(Product.category).where(
        Product.brand_id == b.id, Product.is_active.is_(True)).group_by(Product.category)
        .order_by(func.count(Product.id).desc()).limit(4))]
    catalogue = usable_products(ctx.db, b)
    drafts = dict(ctx.state.get("drafts", {}))
    tokens, out_rows, retries, fallbacks = 0, [], 0, 0
    articles = ctx.state.get("articles") or (b.catalogue_source or {}).get("articles") or []
    from ..generation import product_dict

    pillar_seen: dict[str, int] = {}
    for idx, item in enumerate(rows):
        p = prod_of[item.id]
        pf = product_facts(p) if p else None
        prods = [product_dict(p)] if p else []
        slot = {"index": idx, "date": item.planned_at.isoformat() if item.planned_at else None, "pillar": item.pillar,
                "content_type": item.content_type, "variant": item.variant_label, "platform": item.platform,
                "occasion": params.get("occasion"), "festival": ctx.state.get("festival"),
                "pillar_index": pillar_seen.get(item.pillar, 0),
                "option_count": params.get("option_count", 1),
                "article": articles[idx % len(articles)] if articles else None}
        gen_out, t = gen.slot_content(_gen_brief(ctx), slot, prods)
        tokens += t
        pillar_seen[item.pillar] = pillar_seen.get(item.pillar, 0) + 1
        drafts[str(item.id)] = gen_out.model_dump() | ({"product_ids": [p.id]} if p else {})
        opts, img_issues = facts_img[item.id]
        issues = list(img_issues)
        if item.id in swaps:
            issues.append({"code": "product_substituted", "message": swaps[item.id] + "."})
        if pf and pf.religious:
            issues.append({"code": "religious_concept", "message": f"{pf.name} shows a deity or idol; it isn't named "
                           "or pictured and needs human review.", "needs_review": True})
        if pf and not pf.promotable:
            issues.append({"code": "product_not_promotable", "message": f"{pf.name}: {promotable(p)[1]}; no product "
                           "claims are used."})
        if pf and pf.price is not None and not pf.price_ok:
            issues.append({"code": "price_not_verified", "message": f"{pf.name}: the price isn't fresh or is "
                           "flagged, so no price claim is allowed."})
        if pillar_kind(item.pillar) == "offer":
            issues.append({"code": "offer_unverified", "message": "Offers pillar, but no verified offer or discount "
                           "data exists, so the brief makes no offer."})
        sp = SPECS.get(item.platform) or SPECS["instagram"]
        post_day = _local_date(item.planned_at, tz, today)
        keys = [item.pillar, *(item.pillar or "").split(), (p.category if p else ""), *(v["name"] for v in verified)]
        g = groups.get(item.pillar)
        art = articles[idx % len(articles)] if articles else None
        recent = (done_recent[::-1] + older)[:window]
        facts = B.BriefFacts(
            content_id=item.id, platform=item.platform, platform_label=sp.label, content_type=item.content_type,
            size=(sp.render.width, sp.render.height, sp.render.label), link_in_caption=sp.link_in_caption,
            post_date=post_day, today=today, pillar=item.pillar, pillar_kind=pillar_kind(item.pillar),
            brand_name=b.name,
            objective=((f"{camp.objective_metric}: " if camp and camp.objective_metric else "")
                       + ((camp.objective if camp else "") or b.goals or "Grow engagement"))[:300],
            audience=((camp.audience if camp else "") or b.audience or "")[:300], voice=b.voice or "",
            colors=list(b.colors or []), categories=categories, product=pf, images=opts, festivals=verified,
            unverified_festivals=[h for h in hints if 0 <= (h["start"] - post_day).days <= B.FESTIVAL_WINDOW_DAYS],
            undated_festivals=undated,
            festival_names=[v["name"] for v in verified] + undated + [h["name"] for h in hints],
            wants_festival=pillar_kind(item.pillar) in ("guide", "offer") or bool(params.get("occasion")),
            article={"title": art.get("title"), "excerpt": art.get("excerpt")} if art else None,
            trend_ids=_relevant_findings(findings, keys),
            competitor_ids=[o.id for o in comp_rows if o.content_format == item.content_type][:3],
            competitor_names=comp_names,
            analytics_note=(f"{item.pillar} posts averaged {g['mean_engagement_rate']:.1%} engagement (n={g['n']})"
                            if g and g.get("mean_engagement_rate") is not None else ""),
            recent=recent, qa=qa_feedback(ctx, item, render_fails), prohibited=list(b.prohibited_messaging or []),
            restricted=list(b.restricted_claims or []),
            issues=[{"code": i["code"], "message": i["message"], "needs_review": i.get("needs_review", False)}
                    for i in issues],
            claim_checker=lambda text, _p=p: [c.message for c in check_product_claims(text, b, [_p] if _p else [],
                                                                                       catalogue)
                                              if c.status == "fail"],
            is_synthetic=ctx.settings.is_demo)
        outcome = B.brief_with_retry(facts, roles[item.id])
        brief = outcome.brief
        retries += len(outcome.attempts)
        fallbacks += int(outcome.fallback)
        data = brief.model_dump(mode="json")
        apply(ctx, item, {"creative_brief": data, "image_brief": (gen_out.image_brief if ctx.settings.is_live
                                                                else B.image_brief_text(brief)),
                          "carousel_outline": gen_out.carousel_outline, "title": gen_out.title[:255],
                          "product_ids": [p.id] if p else list(item.product_ids or [])},
              f"Creative brief v{B.SCHEMA_VERSION}: {brief.image_policy}, {brief.angle}"
              + (" (needs review)" if brief.needs_human_review else ""))
        item.rationale = (gen_out.rationale or brief.signals.reason)[:2000]
        done_recent.append(B.RecentPost(headline=brief.headline, tagline=brief.tagline, angle=brief.angle,
                                        layout=brief.style.layout, palette=brief.style.palette))
        out_rows.append({"content_id": item.id, "role": roles[item.id], "summary": B.summary_line(brief),
                         "image_policy": brief.image_policy, "angle": brief.angle, "headline": brief.headline,
                         "festival": brief.festival.model_dump(mode="json") if brief.festival else None,
                         "needs_human_review": brief.needs_human_review,
                         "issues": [i.code for i in brief.data_issues], "attempts": len(outcome.attempts) + 1,
                         "failed_checks": outcome.attempts, "fallback": outcome.fallback})
    ctx.remember("drafts", drafts)
    return {"briefs": out_rows, "data_issues": run_issues, "tokens": tokens, "retries": retries,
            "fallbacks": fallbacks, "repeat_window": window,
            "mix": {r: sum(1 for x in out_rows if x["image_policy"] == r) for r in
                    ("text_only", "may_use_images", "must_use_images")}}


def _gen_brief(ctx: ToolContext) -> dict:
    from .common import brief

    return brief(ctx)
