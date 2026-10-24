"""Database schema for GrowthPilot AI.

Conventions:
* Every tenant row carries ``workspace_id``; all access is scoped through it.
* Datetimes are naive UTC.
* ``is_synthetic`` marks fixture/demo data so it is never presented as real.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid() -> str:
    return uuid.uuid4().hex


# ── enums ────────────────────────────────────────────────────────────────


class Role(StrEnum):
    OWNER = "owner"  # everything: approve, authorise publishing, channels, members
    EDITOR = "editor"  # brand brain, campaigns, content, agent runs; submit for review
    VIEWER = "viewer"  # read-only


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    PINTEREST = "pinterest"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"


PLATFORM_LABELS = {
    Platform.INSTAGRAM: "Instagram",
    Platform.PINTEREST: "Pinterest",
    Platform.FACEBOOK: "Facebook",
    Platform.TIKTOK: "TikTok",
    Platform.YOUTUBE: "YouTube",
}


class ContentType(StrEnum):
    POST = "post"  # single image + caption
    CAROUSEL = "carousel"
    REEL = "reel"
    STORY = "story"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceClass(StrEnum):
    VERIFIED_OBSERVATION = "verified_observation"  # we observed it directly (fetched page, our own data)
    SOURCE_REPORTED = "source_reported"  # a source says so; not independently verified
    INFERENCE = "inference"  # derived by reasoning from other evidence
    HYPOTHESIS = "hypothesis"  # proposed, untested
    UNKNOWN = "unknown"  # not available through connected sources


class ConnectionStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIG_INCOMPLETE = "config_incomplete"
    AWAITING_AUTHORIZATION = "awaiting_authorization"
    AWAITING_PROVIDER_APPROVAL = "awaiting_provider_approval"
    CONNECTED = "connected"  # verified against the provider
    EXPIRED = "expired"
    FAILED = "failed"
    DEMO = "demo"


# ── system / auth ────────────────────────────────────────────────────────


class AppMeta(Base):
    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    # Agent execution limits (per run).
    agent_max_steps: Mapped[int] = mapped_column(Integer, default=60)
    agent_token_budget: Mapped[int] = mapped_column(Integer, default=400_000)
    agent_timeout_minutes: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.EDITOR)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship()


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_verifier_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user: Mapped[User | None] = relationship()


# ── Brand Brain ──────────────────────────────────────────────────────────


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    positioning: Mapped[str] = mapped_column(Text, default="")
    voice: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(160), default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    colors: Mapped[list] = mapped_column(JSON, default=list)  # ["#2F4F3A", ...]
    visual_guidelines: Mapped[str] = mapped_column(Text, default="")
    # Claims policy
    approved_claims: Mapped[list] = mapped_column(JSON, default=list)  # exact claims cleared for use
    restricted_claims: Mapped[list] = mapped_column(JSON, default=list)  # need evidence / owner sign-off
    prohibited_messaging: Mapped[list] = mapped_column(JSON, default=list)  # never allowed
    constraints: Mapped[str] = mapped_column(Text, default="")
    permitted_sources: Mapped[list] = mapped_column(JSON, default=list)  # domains research may fetch
    logo_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL", use_alter=True))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    personas: Mapped[list[Persona]] = relationship(back_populates="brand", cascade="all, delete-orphan")
    products: Mapped[list[Product]] = relationship(back_populates="brand", cascade="all, delete-orphan")


class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    pain_points: Mapped[str] = mapped_column(Text, default="")
    preferred_platforms: Mapped[list] = mapped_column(JSON, default=list)

    brand: Mapped[Brand] = relationship(back_populates="personas")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("brand_id", "sku"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80))  # sofa, bed, dining table, …
    collection: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    dimensions: Mapped[str] = mapped_column(String(160), default="")  # "W 210 × D 92 × H 84 cm"
    materials: Mapped[list] = mapped_column(JSON, default=list)
    finishes: Mapped[list] = mapped_column(JSON, default=list)
    verified_attributes: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"warranty": "5 years"}
    image_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    brand: Mapped[Brand] = relationship(back_populates="products")


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="image")  # image | logo
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload | generated | placeholder
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255))  # path under the asset store
    public_token: Mapped[str] = mapped_column(String(64), default=new_uuid, unique=True)
    alt_text: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ── research & competitors ───────────────────────────────────────────────


class ResearchFinding(Base):
    __tablename__ = "research_findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    topic: Mapped[str] = mapped_column(String(160), default="")
    statement: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(30), default=EvidenceClass.SOURCE_REPORTED)
    source_type: Mapped[str] = mapped_column(String(30))  # web_search | website | competitor | internal | fixture
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_title: Mapped[str] = mapped_column(String(500), default="")
    evidence_excerpt: Mapped[str] = mapped_column(Text, default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Competitor(Base):
    __tablename__ = "competitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    website: Mapped[str] = mapped_column(String(255), default="")
    instagram_url: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    observations: Mapped[list[CompetitorObservation]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan", order_by="CompetitorObservation.observed_at.desc()"
    )


class CompetitorObservation(Base):
    __tablename__ = "competitor_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(String(30))  # website | fixture
    source_url: Mapped[str | None] = mapped_column(String(1000))
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    content_format: Mapped[str] = mapped_column(String(40), default="")  # post | carousel | reel | article | page
    theme: Mapped[str] = mapped_column(String(160), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")  # short quoted excerpt, never a full copy
    cta: Mapped[str] = mapped_column(String(255), default="")
    product_categories: Mapped[list] = mapped_column(JSON, default=list)
    visible_engagement: Mapped[dict | None] = mapped_column(JSON)  # only what the source exposes publicly
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    competitor: Mapped[Competitor] = relationship(back_populates="observations")


# ── campaigns, hypotheses, experiments ───────────────────────────────────


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL", use_alter=True))
    name: Mapped[str] = mapped_column(String(160))
    objective: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    geography: Mapped[str] = mapped_column(String(160), default="")
    language: Mapped[str] = mapped_column(String(60), default="English")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    platforms: Mapped[list] = mapped_column(JSON, default=list)
    pillars: Mapped[list] = mapped_column(JSON, default=list)
    creative_direction: Mapped[str] = mapped_column(Text, default="")
    ctas: Mapped[list] = mapped_column(JSON, default=list)
    budget_note: Mapped[str] = mapped_column(Text, default="")
    measurement_plan: Mapped[str] = mapped_column(Text, default="")
    success_criteria: Mapped[list] = mapped_column(JSON, default=list)  # [{"metric","comparator","target"}]
    risks: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    product_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    brand: Mapped[Brand] = relationship()
    items: Mapped[list[ContentItem]] = relationship(back_populates="campaign")
    hypotheses: Mapped[list[Hypothesis]] = relationship(back_populates="campaign", cascade="all, delete-orphan",
                                                        order_by="Hypothesis.rank")


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    statement: Mapped[str] = mapped_column(Text)
    mechanism: Mapped[str] = mapped_column(Text, default="")  # why we expect it to work
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)  # ResearchFinding ids
    uncertainty: Mapped[str] = mapped_column(Text, default="")
    validation_method: Mapped[str] = mapped_column(Text, default="")
    scores: Mapped[dict] = mapped_column(JSON, default=dict)  # 1–5 per criterion; heuristic, not probability
    total_score: Mapped[float] = mapped_column(default=0.0)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|selected|supported|refuted|inconclusive
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    campaign: Mapped[Campaign | None] = relationship(back_populates="hypotheses")


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    hypothesis_id: Mapped[int | None] = mapped_column(ForeignKey("hypotheses.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    variants: Mapped[list] = mapped_column(JSON, default=list)  # [{"label":"A","description":...}]
    primary_metric: Mapped[str] = mapped_column(String(60), default="engagement_rate_by_reach")
    success_criteria: Mapped[list] = mapped_column(JSON, default=list)
    min_sample_per_variant: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|running|evaluated
    result: Mapped[dict | None] = mapped_column(JSON)
    conclusion: Mapped[str] = mapped_column(String(30), default="")  # supported|not_supported|inconclusive
    learnings: Mapped[str] = mapped_column(Text, default="")
    next_recommendation: Mapped[str] = mapped_column(Text, default="")
    data_source: Mapped[str] = mapped_column(String(20), default="")  # synthetic | real | mixed | none
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime)

    hypothesis: Mapped[Hypothesis | None] = relationship()


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{"type","ref","summary"}]
    uncertainty: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|accepted|dismissed
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ── content ──────────────────────────────────────────────────────────────


class ChannelConnection(Base):
    __tablename__ = "channel_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    adapter: Mapped[str] = mapped_column(String(30))  # demo_instagram | instagram | webhook
    platform: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    credentials_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted JSON; never returned by the API
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret settings
    account_id: Mapped[str] = mapped_column(String(120), default="")
    account_label: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(30), default=ConnectionStatus.AWAITING_AUTHORIZATION)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContentItem(Base):
    __tablename__ = "content_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"))
    variant_label: Mapped[str] = mapped_column(String(20), default="")
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20), default=Platform.INSTAGRAM)
    content_type: Mapped[str] = mapped_column(String(20), default=ContentType.POST)
    pillar: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    hook: Mapped[str] = mapped_column(String(500), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    cta: Mapped[str] = mapped_column(String(255), default="")
    image_brief: Mapped[str] = mapped_column(Text, default="")
    carousel_outline: Mapped[list] = mapped_column(JSON, default=list)
    video_script: Mapped[str] = mapped_column(Text, default="")
    product_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"))
    slide_asset_ids: Mapped[list] = mapped_column(JSON, default=list)  # carousel slides after the cover
    validation: Mapped[dict | None] = mapped_column(JSON)  # last validation report
    status: Mapped[str] = mapped_column(String(20), default=ContentStatus.DRAFT, index=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime)  # calendar slot (UTC)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # UTC, set when scheduled
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("channel_connections.id", ondelete="SET NULL"))
    generated_by: Mapped[str] = mapped_column(String(80), default="human")
    rationale: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_version: Mapped[int | None] = mapped_column(Integer)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    publish_authorized: Mapped[bool] = mapped_column(Boolean, default=False)  # owner explicitly allowed live publish
    review_note: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    external_id: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(500))
    publish_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    campaign: Mapped[Campaign | None] = relationship(back_populates="items")
    brand: Mapped[Brand] = relationship()
    connection: Mapped[ChannelConnection | None] = relationship()
    asset: Mapped[Asset | None] = relationship()
    revisions: Mapped[list[ContentRevision]] = relationship(
        back_populates="content", cascade="all, delete-orphan", order_by="ContentRevision.version.desc()"
    )
    metrics: Mapped[list[MetricSnapshot]] = relationship(
        back_populates="content", cascade="all, delete-orphan", order_by="MetricSnapshot.captured_at"
    )
    attempts: Mapped[list[PublishAttempt]] = relationship(
        back_populates="content", cascade="all, delete-orphan", order_by="PublishAttempt.attempted_at.desc()"
    )


class ContentRevision(Base):
    __tablename__ = "content_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)  # caption, hashtags, hook, cta, image_brief, … at this version
    source: Mapped[str] = mapped_column(String(80), default="human")
    note: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    content: Mapped[ContentItem] = relationship(back_populates="revisions")


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("channel_connections.id", ondelete="SET NULL"))
    adapter: Mapped[str] = mapped_column(String(30))
    live: Mapped[bool] = mapped_column(Boolean)
    # "<content_id>:v<version>:<attempt>" for failures; successes use "<content_id>:v<version>" so a version can
    # only ever be published once (enforced by the unique constraint).
    idempotency_key: Mapped[str] = mapped_column(String(80))
    success: Mapped[bool] = mapped_column(Boolean)
    external_id: Mapped[str | None] = mapped_column(String(255))
    provider_status: Mapped[str] = mapped_column(String(60), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    content: Mapped[ContentItem] = relationship(back_populates="attempts")


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Raw observations; None means "not available from the source", never zero-filled.
    reach: Mapped[int | None] = mapped_column(Integer)
    views: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    profile_visits: Mapped[int | None] = mapped_column(Integer)
    link_clicks: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))  # synthetic | instagram_api | manual
    raw: Mapped[dict | None] = mapped_column(JSON)

    content: Mapped[ContentItem] = relationship(back_populates="metrics")


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    markdown: Mapped[str] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ── agent execution ──────────────────────────────────────────────────────


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    goal: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(30), default="")
    planner: Mapped[str] = mapped_column(String(40))  # demo-planner | claude:<model>
    status: Mapped[str] = mapped_column(String(30), default=RunStatus.QUEUED, index=True)
    plan: Mapped[list] = mapped_column(JSON, default=list)  # [{"id","tool","purpose","status"}]
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # working memory (ids of produced records, etc.)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer, default=60)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    token_budget: Mapped[int] = mapped_column(Integer, default=400_000)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome_summary: Mapped[str] = mapped_column(Text, default="")
    completion_reason: Mapped[str] = mapped_column(String(60), default="")
    blockers: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)

    steps: Mapped[list[AgentStep]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                  order_by="AgentStep.seq")


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(20))  # observe|plan|tool|evaluate|replan|decision|approval|finish|error
    tool: Mapped[str | None] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text, default="")  # human-readable summary of what/why
    input: Mapped[dict | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|error|skipped|blocked
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[AgentRun] = relationship(back_populates="steps")
