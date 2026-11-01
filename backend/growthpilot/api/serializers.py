"""Model → JSON. Secrets (credentials_enc, tokens, password hashes) are never included."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..models import (
    AgentRun,
    AgentStep,
    ApprovalRequest,
    Asset,
    Brand,
    Campaign,
    ChannelConnection,
    Competitor,
    CompetitorObservation,
    ContentItem,
    Experiment,
    Hypothesis,
    MetricSnapshot,
    Persona,
    Product,
    PublishAttempt,
    Recommendation,
    Report,
    ResearchFinding,
)


def dt(v: datetime | None) -> str | None:
    return v.replace(tzinfo=UTC).isoformat() if v else None


def local(v: datetime | None, tz: ZoneInfo) -> str | None:
    return v.replace(tzinfo=UTC).astimezone(tz).isoformat() if v else None


def brand(b: Brand) -> dict:
    src = dict(b.catalogue_source or {})
    return {k: getattr(b, k) for k in (
        "id", "name", "description", "positioning", "voice", "tone", "audience", "location", "goals", "website",
        "colors", "visual_guidelines", "approved_claims", "restricted_claims", "prohibited_messaging", "constraints",
        "permitted_sources", "logo_asset_id", "is_synthetic", "content_pillars", "languages", "marketing_objectives",
        "platform_preferences", "posting_constraints", "campaign_budget_usd", "fonts", "profile_sources")} | {
        "updated_at": dt(b.updated_at),
        "catalogue_source": {k: src.get(k) for k in ("kind", "label", "base_url", "last_synced_at", "last_status",
                                                     "last_error", "snapshot", "products_seen", "image_audit",
                                                     "catalogue_total")},
        "festivals": [{k: f.get(k) for k in ("name", "nameKn", "slug", "importance", "itemsNeeded", "poojaVidhi")}
                      for f in src.get("festivals") or []],
        "articles": [{k: a.get(k) for k in ("title", "slug", "excerpt")} for a in src.get("articles") or []]}


def persona(p: Persona) -> dict:
    return {k: getattr(p, k) for k in ("id", "name", "description", "goals", "pain_points", "preferred_platforms")}


def product(p: Product) -> dict:
    from ..catalogue import freshness

    return {k: getattr(p, k) for k in ("id", "sku", "name", "category", "collection", "description", "currency",
                                       "dimensions", "materials", "finishes", "verified_attributes", "image_asset_id",
                                       "is_active", "is_synthetic", "source_url", "source_ref", "stock",
                                       "allow_backorder", "variants", "image_urls", "image_kind", "name_local", "flags",
                                       "delivery", "data_quality")} | {
        "price": float(p.price) if p.price is not None else None, "mrp": float(p.mrp) if p.mrp is not None else None,
        "retrieved_at": dt(p.retrieved_at), "freshness": freshness(p)}


SOURCE_LABELS = {"upload": "Uploaded", "catalogue": "Real product photo (store)", "stock": "Generic stock image",
                 "rendered": "Rendered by GrowthPilot", "ai_background": "AI-generated background",
                 "placeholder": "Placeholder"}


def asset(a: Asset, full: bool = False) -> dict:
    meta = a.meta or {}
    source_label = ("Gemini-generated image" if meta.get("generation_mode") == "full_image"
                    else SOURCE_LABELS.get(a.source, a.source))
    d = {"id": a.id, "kind": a.kind, "source": a.source, "source_label": source_label,
         "filename": a.filename, "content_type": a.content_type, "size_bytes": a.size_bytes, "width": a.width,
         "height": a.height, "alt_text": a.alt_text, "is_synthetic": a.is_synthetic, "url": f"/api/assets/{a.id}/file",
         "placeholder": a.source == "placeholder", "origin_url": a.origin_url, "sha256": a.sha256,
         "campaign_id": a.campaign_id, "created_at": dt(a.created_at),
         "template": meta.get("template"), "platform": meta.get("platform"), "content_id": meta.get("content_id"),
         "photo_kind": meta.get("photo_kind"), "background": meta.get("background"),
         "checks_ok": meta.get("ok") if meta else None}
    if full:
        d["meta"] = meta
    return d


def approval_request(r: ApprovalRequest) -> dict:
    return {k: getattr(r, k) for k in ("id", "run_id", "kind", "title", "detail", "payload", "status",
                                       "decided_by", "decision_note")} | {
        "requested_at": dt(r.requested_at), "decided_at": dt(r.decided_at)}


def finding(f: ResearchFinding) -> dict:
    return {k: getattr(f, k) for k in ("id", "topic", "statement", "classification", "source_type", "source_url",
                                       "source_title", "evidence_excerpt", "is_synthetic", "run_id")} | {
        "retrieved_at": dt(f.retrieved_at)}


def observation(o: CompetitorObservation) -> dict:
    return {k: getattr(o, k) for k in ("id", "competitor_id", "source_type", "source_url", "content_format", "theme",
                                       "excerpt", "cta", "product_categories", "visible_engagement", "is_synthetic")} | {
        "observed_at": dt(o.observed_at), "published_at": dt(o.published_at)}


def competitor(c: Competitor, with_obs: bool = False) -> dict:
    d = {k: getattr(c, k) for k in ("id", "name", "website", "instagram_url", "notes", "is_synthetic")}
    d["observation_count"] = len(c.observations)
    if with_obs:
        d["observations"] = [observation(o) for o in c.observations]
    return d


def hypothesis(h: Hypothesis) -> dict:
    return {k: getattr(h, k) for k in ("id", "campaign_id", "statement", "mechanism", "evidence_ids", "uncertainty",
                                       "validation_method", "scores", "total_score", "rank", "selected", "status")}


def experiment(e: Experiment) -> dict:
    return {k: getattr(e, k) for k in ("id", "campaign_id", "hypothesis_id", "name", "variants", "primary_metric",
                                       "success_criteria", "min_sample_per_variant", "status", "result", "conclusion",
                                       "learnings", "next_recommendation", "data_source", "is_synthetic",
                                       "intervention", "baseline", "evaluation_window_days", "comparison_method",
                                       "confidence")} | {
        "created_at": dt(e.created_at), "evaluated_at": dt(e.evaluated_at)}


def recommendation(r: Recommendation) -> dict:
    return {k: getattr(r, k) for k in ("id", "campaign_id", "experiment_id", "run_id", "title", "detail", "rationale",
                                       "evidence", "uncertainty", "priority", "status", "is_synthetic",
                                       "proposed_change", "decided_by")} | {
        "created_at": dt(r.created_at), "decided_at": dt(r.decided_at)}


def campaign(c: Campaign, counts: dict | None = None) -> dict:
    d = {k: getattr(c, k) for k in ("id", "brand_id", "run_id", "name", "objective", "audience", "geography",
                                    "language", "platforms", "pillars", "creative_direction", "ctas", "budget_note",
                                    "measurement_plan", "success_criteria", "risks", "assumptions", "product_ids",
                                    "status", "is_synthetic", "objective_metric", "channel_mix", "budget_usd",
                                    "budget_allocation", "baseline", "evaluation_window_days", "strategy")}
    d |= {"start_date": c.start_date.isoformat() if c.start_date else None,
          "end_date": c.end_date.isoformat() if c.end_date else None, "created_at": dt(c.created_at)}
    if counts is not None:
        d["counts"] = counts
    return d


def metric(m: MetricSnapshot) -> dict:
    return {k: getattr(m, k) for k in ("id", "reach", "views", "likes", "comments", "shares", "saves",
                                       "profile_visits", "link_clicks", "source")} | {"captured_at": dt(m.captured_at)}


def attempt(a: PublishAttempt) -> dict:
    return {k: getattr(a, k) for k in ("id", "adapter", "live", "success", "external_id", "provider_status", "summary",
                                       "error", "idempotency_key")} | {"attempted_at": dt(a.attempted_at)}


def content(i: ContentItem, tz: ZoneInfo, full: bool = False) -> dict:
    d = {k: getattr(i, k) for k in (
        "id", "campaign_id", "experiment_id", "variant_label", "run_id", "platform", "master_id", "content_type",
        "pillar", "title",
        "hook", "caption", "hashtags", "cta", "image_brief", "carousel_outline", "video_script", "product_ids",
        "evidence_ids", "asset_id", "slide_asset_ids", "validation", "canva_poster", "status", "connection_id", "generated_by",
        "rationale", "version", "approved_version", "approved_by", "publish_authorized", "review_note", "external_id",
        "external_url", "publish_verified", "last_error", "is_synthetic", "approved_hash", "creative_brief")}
    d |= {"planned_at": dt(i.planned_at), "scheduled_at": dt(i.scheduled_at), "published_at": dt(i.published_at),
          "approved_at": dt(i.approved_at), "updated_at": dt(i.updated_at),
          "planned_local": local(i.planned_at, tz), "scheduled_local": local(i.scheduled_at, tz),
          "campaign_name": i.campaign.name if i.campaign else None,
          "brand_name": i.brand.name if i.brand else None,
          "connection_name": i.connection.name if i.connection else None,
          "connection_adapter": i.connection.adapter if i.connection else None,
          "connection_live": bool(i.connection and not i.connection.adapter.startswith("demo_")),
          "asset_url": f"/api/assets/{i.asset_id}/file" if i.asset_id else None,
          "validation_current": bool(i.validation and i.validation.get("version") == i.version)}
    if full:
        d["revisions"] = [{"version": r.version, "source": r.source, "note": r.note, "snapshot": r.snapshot,
                           "edited_by": r.edited_by, "created_at": dt(r.created_at)} for r in i.revisions]
        d["attempts"] = [attempt(a) for a in i.attempts]
        d["metrics"] = [metric(m) for m in i.metrics]
    return d


def connection(c: ChannelConnection, adapter_info: dict | None = None) -> dict:
    return {"id": c.id, "adapter": c.adapter, "platform": c.platform, "name": c.name, "account_id": c.account_id,
            "account_label": c.account_label, "status": c.status, "token_expires_at": dt(c.token_expires_at),
            "last_verified_at": dt(c.last_verified_at), "last_error": c.last_error,
            "config": {k: v for k, v in (c.config or {}).items() if k in ("url",)}, "adapter_info": adapter_info}


def run(r: AgentRun, with_steps: bool = False, after_seq: int = 0) -> dict:
    d = {k: getattr(r, k) for k in ("id", "goal", "intent", "planner", "status", "plan", "step_count", "max_steps",
                                    "tokens_used", "token_budget", "cancel_requested", "outcome_summary",
                                    "completion_reason", "blockers", "error", "campaign_id", "brand_id", "cost_usd",
                                    "cost_budget_usd", "pause_requested", "recoveries")}
    st = r.state or {}
    d |= {"created_at": dt(r.created_at), "started_at": dt(r.started_at), "finished_at": dt(r.finished_at),
          "outputs": {k: st.get(k) for k in ("campaign_id", "content_ids", "variant_ids", "asset_ids", "finding_ids",
                                             "hypothesis_ids", "selected_hypothesis_id", "experiment_id",
                                             "awaiting_ids", "scheduled_ids", "report_id", "next_experiment_id", "gaps",
                                             "brand_snapshot", "awaiting_budget_request") if st.get(k)},
          "params": st.get("params", {}), "approved_extra_usd": st.get("approved_extra_usd", 0.0)}
    if with_steps:
        d["steps"] = [step(s) for s in r.steps if s.seq > after_seq]
    return d


def step(s: AgentStep) -> dict:
    return {k: getattr(s, k) for k in ("seq", "phase", "tool", "message", "input", "output", "status", "is_mock",
                                       "attempt", "duration_ms", "tokens", "role", "effect", "cost_usd",
                                       "evidence_ids")} | {"created_at": dt(s.created_at)}


def report(r: Report, with_body: bool = False) -> dict:
    d = {"id": r.id, "campaign_id": r.campaign_id, "run_id": r.run_id, "title": r.title, "data_source": r.data_source,
         "created_at": dt(r.created_at)}
    if with_body:
        d["markdown"] = r.markdown
    return d
