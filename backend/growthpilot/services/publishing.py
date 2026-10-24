"""Publishes due, approved content through its adapter, then verifies with the provider.

Checks are repeated at the moment of publishing, not only when scheduling. Each content version can be
published at most once: successes are recorded under the idempotency key "<id>:v<version>", which is unique.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..adapters import AdapterError, get_adapter
from ..adapters.base import PublishPayload
from ..config import get_settings
from ..models import ConnectionStatus, ContentItem, ContentStatus, PublishAttempt, utcnow
from ..security import redact
from .assets import public_url
from .connections import context
from .content import approval_intact
from .validation import final_caption, item_assets, validate_item

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_LATENESS = timedelta(hours=6)


def success_key(item: ContentItem) -> str:
    return f"{item.id}:v{item.version}"


def _claim(db: Session, item_id: int) -> bool:
    res = db.execute(update(ContentItem).where(ContentItem.id == item_id,
                                               ContentItem.status == ContentStatus.SCHEDULED)
                     .values(status=ContentStatus.PUBLISHING, updated_at=utcnow()))
    db.commit()
    return res.rowcount == 1


def _fail(db: Session, item: ContentItem, msg: str) -> None:
    item.status = ContentStatus.FAILED
    item.last_error = msg
    audit.record(db, "content.publish_failed", workspace_id=item.workspace_id, target_type="content",
                 target_id=item.id, error=msg)


def _record_failure(db: Session, item: ContentItem, adapter_key: str, live: bool, msg: str, triggered_by) -> int:
    n = db.execute(select(func.count(PublishAttempt.id)).where(PublishAttempt.content_id == item.id,
                                                               PublishAttempt.success.is_(False))).scalar_one()
    db.add(PublishAttempt(content_id=item.id, connection_id=item.connection_id, adapter=adapter_key, live=live,
                          idempotency_key=f"{item.id}:v{item.version}:fail{n + 1}", success=False, error=msg,
                          triggered_by=triggered_by))
    return n + 1


def publish_item(db: Session, item_id: int, *, triggered_by: int | None = None) -> ContentItem | None:
    s = get_settings()
    item = db.get(ContentItem, item_id)
    if item is None or item.status != ContentStatus.SCHEDULED:
        return None
    conn = item.connection
    try:
        adapter = get_adapter(conn.adapter) if conn else None
    except AdapterError:
        adapter = None
    if adapter and adapter.external and not s.live_publishing_enabled:
        item.last_error = "Waiting: live publishing is turned off (LIVE_PUBLISHING_ENABLED=false)."
        db.commit()
        return item
    if item.scheduled_at and utcnow() - item.scheduled_at > MAX_LATENESS:
        _fail(db, item, "Missed its publishing window by more than 6 hours; reschedule it.")
        db.commit()
        return item
    if not _claim(db, item.id):
        return None
    db.refresh(item)

    # Re-check everything at send time.
    if conn is None or adapter is None or conn.workspace_id != item.workspace_id:
        _fail(db, item, "Its connection is missing or not allowed in this mode.")
        db.commit()
        return item
    if item.approved_version != item.version or item.approved_by is None or not approval_intact(db, item):
        _fail(db, item, "Content or media changed after approval; it needs approval again.")
        db.commit()
        return item
    if adapter.external and not item.publish_authorized:
        _fail(db, item, "Publishing to a real account wasn't authorised for this version.")
        db.commit()
        return item
    report = validate_item(db, item)
    if report.failures:
        _fail(db, item, "Validation failed: " + "; ".join(c.message for c in report.failures[:3]))
        db.commit()
        return item
    existing = db.execute(select(PublishAttempt).where(PublishAttempt.idempotency_key == success_key(item))
                          ).scalar_one_or_none()
    if existing is not None:
        # Already published this exact version (e.g. crash after success); never post twice.
        item.status = ContentStatus.PUBLISHED
        item.external_id = existing.external_id
        db.commit()
        return item

    assets = item_assets(db, item)
    payload = PublishPayload(
        content_id=item.id, version=item.version, platform=item.platform, content_type=item.content_type,
        caption=final_caption(item),
        image_urls=[public_url(a) if adapter.external else f"local-asset:{a.id}" for a in assets],
        alt_text=assets[0].alt_text if assets else "",
    )
    try:
        ctx = context(db, conn)
        result = adapter.publish(ctx, payload)
    except AdapterError as exc:
        msg = redact(str(exc))
        n = _record_failure(db, item, conn.adapter, adapter.external, msg, triggered_by)
        if exc.reauth:
            conn.status = ConnectionStatus.EXPIRED
            conn.last_error = msg
        if exc.retryable and n < MAX_ATTEMPTS:
            item.status = ContentStatus.SCHEDULED
            item.scheduled_at = utcnow() + timedelta(minutes=2 ** n)
            item.last_error = f"Retry {n}/{MAX_ATTEMPTS - 1} scheduled: {msg}"
        else:
            _fail(db, item, msg)
        db.commit()
        return item
    except Exception as exc:  # noqa: BLE001 - never leave an item stuck
        log.exception("unexpected publish error for content %s", item.id)
        _fail(db, item, f"Unexpected error ({type(exc).__name__}). Check the platform before retrying.")
        db.commit()
        return item

    try:
        db.add(PublishAttempt(content_id=item.id, connection_id=conn.id, adapter=conn.adapter, live=adapter.external,
                              idempotency_key=success_key(item), success=True, external_id=result.external_id,
                              provider_status=result.provider_status, summary=result.summary,
                              triggered_by=triggered_by))
        db.flush()
    except IntegrityError:
        db.rollback()
        item = db.get(ContentItem, item_id)
        item.status = ContentStatus.PUBLISHED
        db.commit()
        return item
    item.status = ContentStatus.PUBLISHED
    item.published_at = utcnow()
    item.external_id = result.external_id
    item.external_url = result.url
    item.last_error = None
    audit.record(db, "content.published", workspace_id=item.workspace_id, user_id=triggered_by,
                 target_type="content", target_id=item.id, adapter=conn.adapter, live=adapter.external,
                 external_id=result.external_id, version=item.version)
    db.commit()
    verify(db, item)
    return item


def verify(db: Session, item: ContentItem) -> str:
    """Ask the provider whether the post really exists. Returns the provider state."""
    if not item.external_id or not item.connection:
        return "unknown"
    try:
        adapter = get_adapter(item.connection.adapter)
        st = adapter.publication_status(context(db, item.connection), item.external_id)
    except AdapterError as exc:
        item.last_error = f"Published, but verification failed: {redact(str(exc))}"
        db.commit()
        return "error"
    item.publish_verified = st.state == "published"
    if st.url:
        item.external_url = st.url
    if st.state != "published":
        item.last_error = f"Provider status: {st.state}. {st.detail}".strip()
    db.commit()
    return st.state


def run_due(db: Session, limit: int = 20) -> int:
    ids = db.execute(select(ContentItem.id).where(ContentItem.status == ContentStatus.SCHEDULED,
                                                  ContentItem.scheduled_at <= utcnow())
                     .order_by(ContentItem.scheduled_at).limit(limit)).scalars().all()
    return sum(1 for i in ids if publish_item(db, i) is not None)


def recover_stuck(db: Session) -> None:
    """Items left in 'publishing' by a crash are failed for a human to check — never auto-republished."""
    cutoff = utcnow() - timedelta(minutes=10)
    for item in db.execute(select(ContentItem).where(ContentItem.status == ContentStatus.PUBLISHING,
                                                     ContentItem.updated_at < cutoff)).scalars().all():
        _fail(db, item, "Publishing was interrupted. Check the platform before retrying to avoid a duplicate.")
    db.commit()
