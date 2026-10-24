from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class AdapterError(RuntimeError):
    """A provider call failed. Message is safe to show (no secrets)."""

    def __init__(self, message: str, *, retryable: bool = False, reauth: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.reauth = reauth


@dataclass
class Capabilities:
    oauth: bool = False
    identity: bool = False
    validation: bool = True
    publish: bool = False
    scheduling: str = "app-managed"  # app-managed | native | none
    status_verification: bool = False
    analytics: bool = False
    content_types: tuple[str, ...] = ("post",)


@dataclass
class PublishPayload:
    content_id: int
    version: int
    platform: str
    content_type: str
    caption: str  # final text including hashtags
    image_urls: list[str] = field(default_factory=list)  # public URLs (live) or local refs (demo)
    alt_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    external_id: str
    url: str | None
    provider_status: str
    summary: str


@dataclass
class StatusResult:
    state: str  # published | pending | failed | not_found | unknown
    url: str | None = None
    detail: str = ""


@dataclass
class AccountInfo:
    account_id: str
    label: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Metrics:
    reach: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    profile_visits: int | None = None
    link_clicks: int | None = None
    raw: dict[str, Any] | None = None


@dataclass
class ConnectionContext:
    connection_id: int
    account_id: str
    config: dict[str, Any]
    credentials: dict[str, Any]
    save_credentials: Callable[[dict[str, Any]], None] = lambda _c: None


@dataclass
class Issue:
    code: str
    message: str
    severity: str = "error"  # error | warning


class PlatformAdapter(Protocol):
    key: str
    platform: str
    label: str
    external: bool  # contacts a third party → live mode only
    maturity: str  # mock | implemented-unverified | verified
    capabilities: Capabilities

    def verify_connection(self, ctx: ConnectionContext) -> AccountInfo: ...
    def publish(self, ctx: ConnectionContext, payload: PublishPayload) -> PublishResult: ...
    def publication_status(self, ctx: ConnectionContext, external_id: str) -> StatusResult: ...
    def fetch_metrics(self, ctx: ConnectionContext, external_id: str, *, hours_since: float, hints: dict) -> Metrics | None: ...
