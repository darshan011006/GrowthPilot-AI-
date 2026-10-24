"""Distribution Agent tools: platform readiness, calendar, platform variants, approval, scheduling, publishing."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select

from ...adapters import all_adapters, available_adapters, live_adapter_for
from ...models import (
    ApprovalRequest,
    Campaign,
    ChannelConnection,
    ConnectionStatus,
    ContentItem,
    ContentStatus,
    Experiment,
    Hypothesis,
    Workspace,
    utcnow,
)
from ...platforms import ORDER, SPECS
from ...services import analytics, publishing, seasonal
from ...services import content as content_service
from ...services import variants as variants_service
from ...services.content import add_revision
from ...services.errors import WorkflowError
from ..generation import pillar_kind, product_dict
from ..registry import (
    Effect,
    Permission,
    Role,
    ToolBlocked,
    ToolContext,
    ToolError,
    ToolInput,
    ToolResult,
    tool,
)
from .common import brand, brief, generator, items, products, promotable
from .creative import render_item

D = Role.DISTRIBUTION
def _connections(ctx: ToolContext) -> dict[str, ChannelConnection]:
    allowed = available_adapters()
    out: dict[str, ChannelConnection] = {}
    for c in ctx.db.execute(select(ChannelConnection).where(ChannelConnection.workspace_id == ctx.workspace_id,
                                                            ChannelConnection.status.in_([ConnectionStatus.CONNECTED,
                                                                                          ConnectionStatus.DEMO]))
                            ).scalars():
        if c.adapter in allowed and c.platform not in out:
            out[c.platform] = c
    return out


# ── check_platform_capabilities ──────────────────────────────────────────


class CapabilitiesIn(ToolInput):
    platforms: list[str] = Field(default_factory=list, description="Empty = the campaign's platforms.")


@tool("check_platform_capabilities", "For each platform: supported formats and limits, whether a connected account "
      "exists in this mode, whether a live adapter is implemented, what can be published (images, carousels, text, "
      "video) and what's still needed from you.", CapabilitiesIn, Permission.READ, role=D,
      effects=(Effect.READ_ONLY,))
def check_platform_capabilities(ctx: ToolContext, inp: CapabilitiesIn) -> ToolResult:
    plats = [p for p in (inp.platforms or ctx.state.get("platforms") or ctx.state.get("params", {}).get("platforms")
                         or ["instagram"]) if p in SPECS]
    conns = _connections(ctx)
    rows = []
    for key in sorted(dict.fromkeys(plats), key=ORDER.index):
        sp = SPECS[key]
        conn = conns.get(key)
        live = live_adapter_for(key)
        image_types = [t for t in sp.content_types if t in ("post", "carousel")]
        rows.append({
            "platform": key, "label": sp.label, "content_types": list(sp.content_types),
            "can_publish_images": bool(image_types), "caption_max": sp.caption_max, "hashtags_max": sp.hashtags_max,
            "carousel_max": sp.carousel_max, "render": sp.as_dict()["render"], "connected": conn is not None,
            "connection": {"id": conn.id, "adapter": conn.adapter, "label": conn.account_label} if conn else None,
            "simulated": bool(conn and not all_adapters()[conn.adapter].external),
            "live_adapter": live.maturity if live else "not-implemented",
            "needs_from_you": list(sp.needs_from_you) if not (live and conn and not ctx.settings.is_demo) else [],
            "rate_limits": sp.rate_limits, "verified": sp.verified,
        })
    ctx.remember("platform_readiness", {r["platform"]: {"connected": r["connected"],
                                                        "images": r["can_publish_images"]} for r in rows})
    ready = [r["label"] for r in rows if r["connected"] and r["can_publish_images"]]
    return ToolResult(f"{len(rows)} platform(s): ready to schedule images on {', '.join(ready) or 'none'}"
                      + ("" if ctx.settings.is_live else " (simulated demo adapters)") + ".", {"platforms": rows},
                      is_mock=ctx.settings.is_demo)


# ── prepare_schedule ─────────────────────────────────────────────────────


class ScheduleIn(ToolInput):
    days: int = Field(default=7, ge=1, le=14)
    start_date: date | None = None
    occasion: str | None = None
    category: str | None = None
    commit: bool = Field(default=False, description="false = create the calendar slots; true = schedule items a "
                                                    "person has approved, on connected accounts.")
    content_ids: list[int] = Field(default_factory=list)


def _times(b, idx: int) -> time:
    pc = b.posting_constraints or {}
    slots = pc.get("posting_times") or ["13:00", "19:30"]
    hh, mm = (slots[idx % len(slots)] + ":00").split(":")[:2]
    return time(int(hh), int(mm))


def _pillars(b, occasion: str | None) -> tuple[list[str], list[str]]:
    pillars = list(b.content_pillars or [])
    if not pillars:  # furniture fixture defaults
        return ["Small-space solutions", "Styling tips"], ["Product spotlight", "Craft & materials"] + (
            ["Festive"] if occasion else [])
    useful = [p for p in pillars if pillar_kind(p) in ("guide", "know_how")] or pillars[:1]
    product = [p for p in pillars if p not in useful and (pillar_kind(p) != "offer" or occasion)] or pillars[-1:]
    return useful, product


@tool("prepare_schedule", "commit=false: create the campaign calendar — an A/B experiment for the selected hypothesis "
      "(with a baseline from the brand's earlier posts) and one main-channel slot per day at the brand's posting "
      "times in the workspace time zone. commit=true: schedule the items a person approved (main posts and channel "
      "variants) on connected accounts; never schedules anything unapproved.", ScheduleIn, Permission.PUBLISH,
      role=D, effects=(Effect.LOCAL_WRITE,))
def prepare_schedule(ctx: ToolContext, inp: ScheduleIn) -> ToolResult:
    if inp.commit:
        return _commit(ctx, inp)
    b = brand(ctx)
    params = ctx.state.get("params", {})
    camp = ctx.db.get(Campaign, ctx.state.get("campaign_id") or 0)
    if camp is None or camp.workspace_id != ctx.workspace_id:
        raise ToolError("No campaign yet. Run create_campaign_plan first.")
    hyp = ctx.db.get(Hypothesis, ctx.state.get("selected_hypothesis_id") or 0)
    ws = ctx.db.get(Workspace, ctx.workspace_id)
    tz = ZoneInfo(ws.timezone or "UTC")
    today_local = datetime.now(tz).date()
    start = max(inp.start_date or today_local + timedelta(days=1), today_local)
    occasion = inp.occasion or params.get("occasion")
    primary = (camp.platforms or ["instagram"])[0]
    metric = camp.objective_metric or "engagement_rate_by_reach"
    base = analytics.baseline(ctx.db, ctx.workspace_id, metric=metric, content_type="post", platform=primary)
    useful, product_pillars = _pillars(b, occasion)
    generic = bool(b.content_pillars)
    exp = Experiment(
        workspace_id=ctx.workspace_id, campaign_id=camp.id, hypothesis_id=hyp.id if hyp else None,
        name=f"{camp.name}: {useful[0]} carousels (B) vs {product_pillars[0]} posts (A)" if generic else
        f"{camp.name}: carousel planning posts (B) vs single product posts (A)",
        variants=[{"label": "A", "description": f"{product_pillars[0]} single-image post (control)"},
                  {"label": "B", "description": f"{useful[0]} carousel (selected hypothesis)"}],
        primary_metric=metric, success_criteria=camp.success_criteria, min_sample_per_variant=3, status="planned",
        intervention=hyp.statement if hyp else "", baseline=base | {"filters": {"platform": primary}},
        evaluation_window_days=camp.evaluation_window_days,
        comparison_method=f"Within {primary}: permutation test on {metric} between variants; lift also reported "
                          "against the brand's earlier posts.", is_synthetic=ctx.settings.is_demo)
    ctx.db.add(exp)
    ctx.db.flush()
    camp.start_date, camp.end_date, camp.status = start, start + timedelta(days=inp.days - 1), "planned"
    camp.baseline = base
    if hyp:
        hyp.campaign_id = camp.id
    occ_day = None
    if occasion:
        for o in seasonal.upcoming(today_local, within_days=120):
            if occasion.lower()[:5] in o["name"].lower():
                occ_day = o["start"]
                break
    prods = products(ctx, ctx.state.get("product_ids", [])) if ctx.state.get("product_ids") else []
    order = {pid: i for i, pid in enumerate(ctx.state.get("product_ids", []))}
    prods = sorted([p for p in prods if promotable(p)[0]],
                   key=lambda p: (0 if (p.stock or 0) > 0 else 1, order.get(p.id, 999)))
    prod_ids = [p.id for p in prods] or camp.product_ids
    gen = generator(ctx)
    ids, festive_used, offer_used = [], False, False
    for d in range(inp.days):
        day = start + timedelta(days=d)
        variant = "B" if d % 2 == 0 else "A"
        if variant == "B":
            pillar, ctype = useful[(d // 2) % len(useful)], "carousel"
        else:
            pillar, ctype = product_pillars[(d // 2) % len(product_pillars)], "post"
            if not generic and occasion and not festive_used and (occ_day is None or day >= occ_day - timedelta(days=10)):
                pillar, festive_used = "Festive", True
            if generic and occasion and pillar_kind(pillar) == "offer":
                if offer_used:
                    pillar = product_pillars[0]
                offer_used = True
        local = datetime.combine(day, _times(b, d), tzinfo=tz)
        item = ContentItem(workspace_id=ctx.workspace_id, brand_id=b.id, campaign_id=camp.id, experiment_id=exp.id,
                           variant_label=variant, run_id=ctx.run.id, platform=primary, content_type=ctype,
                           pillar=pillar, title=f"Day {d + 1}: {pillar}",
                           planned_at=local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
                           product_ids=[prod_ids[d % len(prod_ids)]] if prod_ids else [],
                           generated_by=gen.name, created_by=ctx.run.created_by, is_synthetic=ctx.settings.is_demo)
        ctx.db.add(item)
        ctx.db.flush()
        add_revision(ctx.db, item, gen.name, None, "Calendar slot created")
        ids.append(item.id)
    ctx.remember("experiment_id", exp.id)
    ctx.remember("content_ids", ids)
    times = ", ".join(t.strftime("%H:%M") for t in {_times(b, 0), _times(b, 1)})
    return ToolResult(
        f"Calendar: {len(ids)} {primary} slot(s) {start:%d %b}–{camp.end_date:%d %b} ({tz.key}) at {times}; experiment "
        f"#{exp.id} ({metric}); baseline {base['note'].lower()}", {"campaign_id": camp.id, "experiment_id": exp.id,
                                                                   "content_ids": ids, "baseline": base,
                                                                   "timezone": tz.key}, is_mock=gen.is_mock)


def _commit(ctx: ToolContext, inp: ScheduleIn) -> ToolResult:
    ids = list(inp.content_ids or (ctx.state.get("content_ids", []) + ctx.state.get("variant_ids", [])))
    conns = _connections(ctx)
    scheduled, skipped = [], []
    for item in items(ctx, ids):
        if item.status != ContentStatus.APPROVED:
            skipped.append({"content_id": item.id, "platform": item.platform, "reason": f"status is {item.status}"})
            continue
        conn = conns.get(item.platform)
        if conn is None:
            skipped.append({"content_id": item.id, "platform": item.platform,
                            "reason": f"no connected {SPECS.get(item.platform).label if item.platform in SPECS else item.platform} account"})
            continue
        when = item.planned_at if item.planned_at and item.planned_at > utcnow() else utcnow() + timedelta(minutes=5)
        try:
            content_service.schedule(ctx.db, item, conn, when, user_id=None, role="agent", confirmed=False, actor="agent")
            scheduled.append({"content_id": item.id, "platform": item.platform, "at": when.isoformat(),
                              "connection": conn.name})
        except WorkflowError as exc:
            skipped.append({"content_id": item.id, "platform": item.platform, "reason": str(exc)})
    if not scheduled and skipped and all("no connected" in s["reason"] for s in skipped):
        raise ToolBlocked("No connected account for the approved items' platforms. Connect them on the "
                          "Integrations page.", blocker="not_connected")
    ctx.remember_ids("scheduled_ids", [s["content_id"] for s in scheduled])
    by_platform: dict[str, int] = {}
    for s in scheduled:
        by_platform[s["platform"]] = by_platform.get(s["platform"], 0) + 1
    return ToolResult(f"Scheduled {len(scheduled)} approved item(s) ("
                      + (", ".join(f"{k} {v}" for k, v in by_platform.items()) or "none")
                      + f"); skipped {len(skipped)}. Each platform's status is tracked separately.",
                      {"scheduled": scheduled, "skipped": skipped}, is_mock=ctx.settings.is_demo)


# ── create_platform_variant ──────────────────────────────────────────────


class VariantIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list, description="Main posts; empty = this run's posts.")
    platforms: list[str] = Field(default_factory=list, description="Empty = the campaign's other platforms.")


@tool("create_platform_variant", "For each main post, create a separate item per other platform in the plan: caption "
      "adapted to the platform's tone and limits (facts unchanged), and images re-rendered at the platform's size. "
      "Each variant has its own version, approval, schedule and publication status. Existing variants are kept.",
      VariantIn, Permission.DRAFT, role=D, effects=(Effect.LOCAL_WRITE, Effect.COST))
def create_platform_variant(ctx: ToolContext, inp: VariantIn) -> ToolResult:
    camp = ctx.db.get(Campaign, ctx.state.get("campaign_id") or 0)
    plats = inp.platforms or [p for p in ((camp.platforms if camp else None) or ctx.state.get("platforms") or [])]
    gen = generator(ctx)
    bf = brief(ctx)
    created, kept, briefs, tokens, errors = [], [], [], 0, []
    masters = [m for m in items(ctx, inp.content_ids) if m.master_id is None]
    for m in masters:
        prods = [product_dict(p) for p in products(ctx, m.product_ids)] if m.product_ids else []
        for key in plats:
            if key == m.platform or key not in SPECS:
                continue
            existing = variants_service.existing_variant(ctx.db, m, key)
            if existing is not None:
                kept.append(existing.id)
                continue
            v, t = variants_service.create_variant(ctx.db, m, key, gen, bf, prods, run_id=ctx.run.id,
                                                   created_by=ctx.run.created_by)
            tokens += t
            if v.content_type in ("post", "carousel"):
                try:
                    ctx.remember_ids("asset_ids", render_item(ctx, v))
                except WorkflowError as exc:
                    errors.append({"content_id": v.id, "reason": str(exc)})
            else:
                briefs.append({"content_id": v.id, "platform": key, "reason": f"{SPECS[key].label} can't publish "
                               "this image post; kept as a brief."})
            created.append(v.id)
    ctx.remember_ids("variant_ids", created + kept)
    by_p: dict[str, int] = {}
    for vid in created:
        p = ctx.db.get(ContentItem, vid).platform
        by_p[p] = by_p.get(p, 0) + 1
    return ToolResult(f"Created {len(created)} variant(s) (" + (", ".join(f"{k} {n}" for k, n in by_p.items()) or "none")
                      + f"); kept {len(kept)} existing" + (f"; {len(briefs)} brief-only" if briefs else "") + ".",
                      {"variant_ids": created, "kept": kept, "brief_only": briefs, "errors": errors,
                       "generator": gen.name}, is_mock=gen.is_mock, tokens=tokens)


# ── request_human_approval ───────────────────────────────────────────────


class ApprovalIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list, description="Empty = this run's posts and variants.")
    kind: str = Field(default="content", pattern="^(content|strategy_change|paid_promotion|account_change)$")
    title: str = Field(default="", max_length=255, description="For non-content approvals.")
    detail: str = Field(default="", max_length=4000)


@tool("request_human_approval", "Send verified items (each exact version, platform variant and image) to the Approval "
      "Inbox and pause until a person reviews them. Items that fail verification stay as drafts with the reasons. "
      "kind=strategy_change/paid_promotion/account_change asks a person to approve a consequential non-content "
      "action instead.", ApprovalIn, Permission.APPROVAL, role=D, effects=(Effect.LOCAL_WRITE,))
def request_human_approval(ctx: ToolContext, inp: ApprovalIn) -> ToolResult:
    if inp.kind != "content":
        req = ApprovalRequest(workspace_id=ctx.workspace_id, run_id=ctx.run.id, kind=inp.kind,
                              title=(inp.title or inp.kind.replace("_", " ").title())[:255], detail=inp.detail,
                              payload={"requested_by": "agent"})
        ctx.db.add(req)
        ctx.db.flush()
        ctx.remember("approval_requested", True)
        ctx.remember("awaiting_request_ids", (ctx.state.get("awaiting_request_ids") or []) + [req.id])
        return ToolResult(f"Approval request #{req.id} ({inp.kind}) sent to the Approval Inbox.",
                          {"request_id": req.id, "submitted": [], "already_in_review": []})
    ids = list(inp.content_ids or (ctx.state.get("content_ids", []) + ctx.state.get("variant_ids", [])))
    submitted, held, already = [], [], []
    for item in items(ctx, ids):
        if item.status == ContentStatus.IN_REVIEW:
            already.append(item.id)
            continue
        if item.status not in (ContentStatus.DRAFT, ContentStatus.CHANGES_REQUESTED):
            continue
        v = item.validation or {}
        state_fails = [f["message"] for k, fs in (ctx.state.get("validation_failures") or {}).items()
                       if k.endswith(f":{item.id}") for f in fs]
        if v.get("version") != item.version or not v.get("ok") or state_fails:
            fails = [c["message"] for s in ("product_claims", "brand", "platform") for c in v.get(s, [])
                     if c.get("status") == "fail"] + state_fails
            item.review_note = "Held back by the agent: " + ("; ".join(dict.fromkeys(fails)) or "not verified")
            held.append({"content_id": item.id, "platform": item.platform, "reasons": list(dict.fromkeys(fails))[:5]})
            continue
        content_service.submit(ctx.db, item, user_id=None, role="editor")
        submitted.append(item.id)
    ctx.remember("approval_requested", True)
    ctx.remember("awaiting_ids", submitted + already)
    return ToolResult(f"{len(submitted) + len(already)} item(s) waiting in the Approval Inbox"
                      + (f"; {len(held)} held back with reasons." if held else "."),
                      {"submitted": submitted, "already_in_review": already, "held": held})


# ── publish / verify ─────────────────────────────────────────────────────


class PublishIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list, description="Empty = items this run scheduled.")


@tool("publish_approved_content", "Publish already-scheduled, human-approved items immediately through their "
      "platform adapter. Refuses anything not approved and scheduled, or changed since approval. Each platform's "
      "result is recorded separately.", PublishIn, Permission.PUBLISH, role=D,
      effects=(Effect.PUBLIC_PUBLISH, Effect.EXTERNAL_WRITE))
def publish_approved_content(ctx: ToolContext, inp: PublishIn) -> ToolResult:
    results = []
    for item in items(ctx, inp.content_ids, key="scheduled_ids"):
        if item.status != ContentStatus.SCHEDULED:
            results.append({"content_id": item.id, "platform": item.platform, "result": f"refused: status is {item.status}"})
            continue
        item.scheduled_at = utcnow()
        ctx.db.flush()
        publishing.publish_item(ctx.db, item.id)
        ctx.db.refresh(item)
        results.append({"content_id": item.id, "platform": item.platform, "result": item.status,
                        "external_id": item.external_id, "verified": item.publish_verified, "error": item.last_error})
    if not results:
        raise ToolError("Nothing to publish.")
    ok = sum(1 for r in results if r["result"] == "published")
    return ToolResult(f"Published {ok}/{len(results)}" + (" (simulated)" if ctx.settings.is_demo else "") + ".",
                      {"results": results}, is_mock=ctx.settings.is_demo)


class VerifyPubIn(ToolInput):
    content_ids: list[int] = Field(default_factory=list, description="Empty = items this run scheduled.")


@tool("verify_publication", "Ask each platform whether published items really exist (media/post lookup; simulated "
      "in demo mode) and record permalinks.", VerifyPubIn, Permission.READ, role=D, effects=(Effect.EXTERNAL_READ,))
def verify_publication(ctx: ToolContext, inp: VerifyPubIn) -> ToolResult:
    rows = []
    for item in items(ctx, inp.content_ids, key="scheduled_ids"):
        if item.status != ContentStatus.PUBLISHED:
            rows.append({"content_id": item.id, "platform": item.platform, "state": f"not published ({item.status})"})
            continue
        rows.append({"content_id": item.id, "platform": item.platform, "state": publishing.verify(ctx.db, item),
                     "url": item.external_url})
    ok = sum(1 for r in rows if r["state"] == "published")
    return ToolResult(f"{ok}/{len(rows)} confirmed by the platform.", {"results": rows}, is_mock=ctx.settings.is_demo)

