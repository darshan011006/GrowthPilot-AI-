"""Model → JSON. Secrets (credentials_enc, tokens, password hashes) are never included."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ..models import (
    AgentRun,
    AgentStep,
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
    return {k: getattr(b, k) for k in (
        "id", "name", "description", "positioning", "voice", "tone", "audience", "location", "goals", "website",
        "colors", "visual_guidelines", "approved_claims", "restricted_claims", "prohibited_messaging", "constraints",
        "permitted_sources", "logo_asset_id", "is_synthetic")} | {"updated_at": dt(b.updated_at)}


def persona(p: Persona) -> dict:
    return {k: getattr(p, k) for k in ("id", "name", "description", "goals", "pain_points", "preferred_platforms")}


def product(p: Product) -> dict:
    return {k: getattr(p, k) for k in ("id", "sku", "name", "category", "collection", "description", "currency",
                                       "dimensions", "materials", "finishes", "verified_attributes", "image_asset_id",
                                       "is_active", "is_synthetic")} | {
        "price": float(p.price) if p.price is not None else None}


def asset(a: Asset) -> dict:
    return {"id": a.id, "kind": a.kind, "source": a.source, "filename": a.filename, "content_type": a.content_type,
            "size_bytes": a.size_bytes, "width": a.width, "height": a.height, "alt_text": a.alt_text,
            "is_synthetic": a.is_synthetic, "url": f"/api/assets/{a.id}/file", "placeholder": a.source == "placeholder"}


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
                                       "learnings", "next_recommendation", "data_source", "is_synthetic")} | {
        "created_at": dt(e.created_at), "evaluated_at": dt(e.evaluated_at)}


def recommendation(r: Recommendation) -> dict:
    return {k: getattr(r, k) for k in ("id", "campaign_id", "experiment_id", "run_id", "title", "detail", "rationale",
                                       "evidence", "uncertainty", "priority", "status", "is_synthetic")} | {
        "created_at": dt(r.created_at)}


def campaign(c: Campaign, counts: dict | None = None) -> dict:
    d = {k: getattr(c, k) for k in ("id", "brand_id", "run_id", "name", "objective", "audience", "geography",
                                    "language", "platforms", "pillars", "creative_direction", "ctas", "budget_note",
                                    "measurement_plan", "success_criteria", "risks", "assumptions", "product_ids",
                                    "status", "is_synthetic")}
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
        "id", "campaign_id", "experiment_id", "variant_label", "run_id", "platform", "content_type", "pillar", "title",
        "hook", "caption", "hashtags", "cta", "image_brief", "carousel_outline", "video_script", "product_ids",
        "evidence_ids", "asset_id", "slide_asset_ids", "validation", "status", "connection_id", "generated_by",
        "rationale", "version", "approved_version", "approved_by", "publish_authorized", "review_note", "external_id",
        "external_url", "publish_verified", "last_error", "is_synthetic")}
    d |= {"planned_at": dt(i.planned_at), "scheduled_at": dt(i.scheduled_at), "published_at": dt(i.published_at),
          "approved_at": dt(i.approved_at), "updated_at": dt(i.updated_at),
          "planned_local": local(i.planned_at, tz), "scheduled_local": local(i.scheduled_at, tz),
          "campaign_name": i.campaign.name if i.campaign else None,
          "connection_name": i.connection.name if i.connection else None,
          "connection_adapter": i.connection.adapter if i.connection else None,
          "connection_live": bool(i.connection and i.connection.adapter != "demo_instagram"),
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
                                    "completion_reason", "blockers", "error", "campaign_id", "brand_id")}
    st = r.state or {}
    d |= {"created_at": dt(r.created_at), "started_at": dt(r.started_at), "finished_at": dt(r.finished_at),
          "outputs": {k: st.get(k) for k in ("campaign_id", "content_ids", "finding_ids", "hypothesis_ids",
                                             "selected_hypothesis_id", "experiment_id", "awaiting_ids", "report_id",
                                             "next_experiment_id", "gaps") if st.get(k)},
          "params": st.get("params", {})}
    if with_steps:
        d["steps"] = [step(s) for s in r.steps if s.seq > after_seq]
    return d


def step(s: AgentStep) -> dict:
    return {k: getattr(s, k) for k in ("seq", "phase", "tool", "message", "input", "output", "status", "is_mock",
                                       "attempt", "duration_ms", "tokens")} | {"created_at": dt(s.created_at)}


def report(r: Report, with_body: bool = False) -> dict:
    d = {"id": r.id, "campaign_id": r.campaign_id, "run_id": r.run_id, "title": r.title, "data_source": r.data_source,
         "created_at": dt(r.created_at)}
    if with_body:
        d["markdown"] = r.markdown
    return d
