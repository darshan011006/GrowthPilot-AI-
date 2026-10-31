"""Catalogue ingestion with provenance, freshness and data-quality checks.

Connectors return normalised product dictionaries; ``sync`` upserts them into ``Product`` rows keeping the
source URL, the source's own id, and the retrieval time for every fact. Nothing is invented: fields the source
doesn't provide stay empty, and suspicious values are flagged rather than "fixed".
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..models import Asset, Brand, Product, utcnow
from ..research.net import domain_allowed, host_of

log = logging.getLogger(__name__)


class CatalogueError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class CatalogueSource(Protocol):
    kind: str
    label: str

    def list_products(self, *, limit: int | None = None) -> list[dict]: ...
    def get_product(self, ref: str) -> dict | None: ...
    def brand_content(self) -> dict: ...


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    photos_downloaded: int = 0
    changes: list[dict] = field(default_factory=list)  # [{"sku","field","old","new"}]
    errors: list[str] = field(default_factory=list)
    source: str = ""
    retrieved_at: str = ""
    snapshot: bool = False

    def as_dict(self) -> dict:
        return self.__dict__ | {"changes": self.changes[:200]}


PRODUCT_FIELDS = ("name", "category", "collection", "description", "price", "mrp", "currency", "stock",
                  "allow_backorder", "variants", "image_urls", "image_kind", "name_local", "flags", "delivery",
                  "source_url", "data_quality", "verified_attributes", "materials")
TRACKED = ("price", "mrp", "stock", "allow_backorder", "name", "image_kind")


def parse_time(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(UTC).replace(tzinfo=None) if d.tzinfo else d


def freshness(p: Product, now: datetime | None = None) -> dict:
    """fresh (< CATALOGUE_FRESH_HOURS) | aging (< 7 days) | stale | manual (entered by a person, no source)."""
    if p.retrieved_at is None:
        return {"state": "manual", "age_hours": None, "label": "Entered manually (no source timestamp)"}
    now = now or utcnow()
    hours = (now - p.retrieved_at).total_seconds() / 3600
    fresh = get_settings().catalogue_fresh_hours
    state = "fresh" if hours < fresh else ("aging" if hours < 24 * 7 else "stale")
    return {"state": state, "age_hours": round(hours, 1),
            "label": {"fresh": "Fresh", "aging": "Getting old", "stale": "Stale"}[state]
            + f" — retrieved {p.retrieved_at:%d %b %Y %H:%M} UTC"}


def _same(a, b) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except Exception:  # noqa: BLE001
            return False
    return a == b


def apply(p: Product, data: dict, retrieved_at: datetime) -> list[dict]:
    """Copy normalised fields onto a product; return the list of tracked changes."""
    changes = []
    for f in PRODUCT_FIELDS:
        if f not in data:
            continue
        new = data[f]
        old = getattr(p, f)
        if f in TRACKED and p.id is not None and not _same(old, new):
            changes.append({"sku": p.sku, "field": f, "old": None if old is None else str(old),
                            "new": None if new is None else str(new)})
        setattr(p, f, new)
    p.source_ref = data.get("source_ref") or p.source_ref
    p.retrieved_at = retrieved_at
    p.is_active = True
    return changes


def sync(db: Session, brand: Brand, source: CatalogueSource, *, records: list[dict] | None = None,
         retrieved_at: datetime | None = None, full: bool = False, limit: int | None = None,
         download_photos: bool = True, user_id: int | None = None, snapshot: bool = False) -> SyncResult:
    """Upsert products from ``source`` (or from pre-fetched ``records``)."""
    now = retrieved_at or utcnow()
    res = SyncResult(source=source.label, retrieved_at=now.isoformat(), snapshot=snapshot)
    if records is None:
        try:
            records = source.list_products(limit=limit)
        except CatalogueError as exc:
            res.errors.append(str(exc))
            brand.catalogue_source = dict(brand.catalogue_source or {}) | {
                "kind": (brand.catalogue_source or {}).get("kind") or source.kind, "last_status": "error",
                "last_error": str(exc)[:300],
                "last_attempt_at": now.isoformat()}
            return res
    existing = {p.source_ref: p for p in db.execute(select(Product).where(Product.brand_id == brand.id,
                                                                          Product.source_ref.is_not(None))).scalars()}
    by_sku = {p.sku: p for p in db.execute(select(Product).where(Product.brand_id == brand.id)).scalars()}
    seen = set()
    names: dict[str, int] = {}
    for r in records:
        names[r["name"].strip().lower()] = names.get(r["name"].strip().lower(), 0) + 1
    for r in records:
        ref = r["source_ref"]
        seen.add(ref)
        when = parse_time(r.pop("_retrieved_at", None)) or now
        if names.get(r["name"].strip().lower(), 0) > 1:
            r["data_quality"] = list(r.get("data_quality", [])) + [
                {"code": "duplicate_name", "message": "Another listing has the same name; check which is current."}]
        p = existing.get(ref) or by_sku.get(r["sku"])
        if p is None:
            p = Product(workspace_id=brand.workspace_id, brand_id=brand.id, sku=r["sku"])
            apply(p, r, when)
            db.add(p)
            db.flush()
            res.created += 1
        else:
            ch = apply(p, r, when)
            res.changes += ch
            if ch:
                res.updated += 1
            else:
                res.unchanged += 1
        if download_photos and p.image_kind == "product_photo" and not p.image_asset_id and p.image_urls:
            try:
                a = download_photo(db, brand, p, p.image_urls[0])
                if a:
                    p.image_asset_id = a.id
                    res.photos_downloaded += 1
            except CatalogueError as exc:
                res.errors.append(f"{p.sku}: {exc}")
    if full:
        for ref, p in existing.items():
            if ref not in seen and p.is_active:
                p.is_active = False
                res.deactivated += 1
    brand.catalogue_source = dict(brand.catalogue_source or {}) | {
        "kind": (brand.catalogue_source or {}).get("kind") or source.kind, "last_source": source.kind,
        "label": source.label, "last_synced_at": now.isoformat(),
        "last_status": "ok" if not res.errors else "partial", "last_error": "; ".join(res.errors)[:300],
        "snapshot": snapshot, "products_seen": len(records)}
    audit.record(db, "catalogue.synced", workspace_id=brand.workspace_id, user_id=user_id, target_type="brand",
                 target_id=brand.id, source=source.kind, created=res.created, updated=res.updated,
                 deactivated=res.deactivated, snapshot=snapshot)
    db.flush()
    return res


def download_photo(db: Session, brand: Brand, p: Product, url: str) -> Asset | None:
    """Store a real product photo from the brand's own store (live mode, or demo when explicitly allowed)."""
    from ..research.net import BlockedURL, host_of, safe_get
    from ..services import assets as asset_service

    s = get_settings()
    if s.is_demo and not s.demo_allow_catalogue_sync:
        return None
    try:
        resp = safe_get(url, max_bytes=asset_service.MAX_UPLOAD_BYTES, allowed_domains=[host_of(url)])
    except BlockedURL as exc:
        raise CatalogueError(f"photo blocked: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise CatalogueError(f"photo download failed ({type(exc).__name__})", retryable=True) from exc
    if resp.status_code != 200:
        raise CatalogueError(f"photo download returned HTTP {resp.status_code}")
    data = resp.content
    ctype = asset_service.sniff(data)
    if ctype is None:
        raise CatalogueError("photo is not a JPEG or PNG")
    w, h = asset_service.image_size(data, ctype)
    key = asset_service.store().save(data, asset_service.ALLOWED[ctype])
    a = Asset(workspace_id=brand.workspace_id, brand_id=brand.id, kind="image", source="catalogue",
              filename=f"{p.sku}{asset_service.ALLOWED[ctype]}", content_type=ctype, size_bytes=len(data), width=w,
              height=h, storage_key=key, alt_text=p.name, origin_url=url, sha256=hashlib.sha256(data).hexdigest(),
              meta={"product_id": p.id, "retrieved_at": utcnow().isoformat(), "kind": "product_photo"})
    db.add(a)
    db.flush()
    return a


def refresh(db: Session, brand: Brand, products: list[Product], source: CatalogueSource | None) -> dict:
    """Re-check the listed products at the source before they're promoted. Returns per-product results."""
    out = {"refreshed": [], "changed": [], "failed": [], "not_refreshed": []}
    if source is None:
        out["not_refreshed"] = [{"sku": p.sku, "reason": "no live catalogue source (snapshot or manual data)",
                                 "freshness": freshness(p)} for p in products]
        return out
    for p in products:
        if not p.source_ref:
            out["not_refreshed"].append({"sku": p.sku, "reason": "entered manually", "freshness": freshness(p)})
            continue
        try:
            data = source.get_product(p.source_ref)
        except CatalogueError as exc:
            out["failed"].append({"sku": p.sku, "error": str(exc)})
            continue
        if data is None:
            p.is_active = False
            p.data_quality = list(p.data_quality or []) + [{"code": "missing_at_source",
                                                            "message": "No longer listed at the source."}]
            out["changed"].append({"sku": p.sku, "field": "listed", "old": "yes", "new": "no"})
            continue
        ch = apply(p, data, utcnow())
        out["refreshed"].append(p.sku)
        out["changed"] += ch
    db.flush()
    return out


def stale_products(products: list[Product], *, max_age: timedelta | None = None) -> list[Product]:
    hours = get_settings().catalogue_fresh_hours
    limit = max_age or timedelta(hours=hours)
    now = utcnow()
    return [p for p in products if p.retrieved_at is not None and now - p.retrieved_at > limit]


def get_source(brand: Brand) -> CatalogueSource | None:
    """The live connector for this brand, or None when only snapshot/manual data is allowed."""
    s = get_settings()
    cfg = brand.catalogue_source or {}
    if cfg.get("kind") != "poojaloka_store_api":
        return None
    # This connector is tied to Poojaloka's catalogue and must never populate another brand.
    if not domain_allowed(host_of(brand.website or ""), ["poojaloka.com"]):
        return None
    if s.is_demo and not s.demo_allow_catalogue_sync:
        return None
    from .poojaloka import PoojalokaStore

    return PoojalokaStore(cfg.get("base_url") or s.poojaloka_api_base)


# Store-specific connectors and the sites their rows come from. A row from one of these sites belongs only to a
# brand whose own website is on that site, even if the row is still marked active (e.g. rows imported before the
# brand changed its website).
STORE_DOMAINS: dict[str, list[str]] = {"poojaloka_store_api": ["poojaloka.com"]}


def foreign_store_product(brand: Brand, p: Product) -> bool:
    """True when the product came from another store's connector (e.g. Poojaloka rows for a non-Poojaloka brand)."""
    if not p.source_url:
        return False
    host, site = host_of(p.source_url), host_of(brand.website or "")
    return any(domain_allowed(host, d) and not domain_allowed(site, d) for d in STORE_DOMAINS.values())


def usable_for_brand(brand: Brand, p: Product | None) -> bool:
    """Whether content for this brand may use the product: active, the brand's own, and not another store's row."""
    return p is not None and p.brand_id == brand.id and bool(p.is_active) and not foreign_store_product(brand, p)


def usable_products(db: Session, brand: Brand, ids: list[int] | None = None) -> list[Product]:
    """The brand's usable products (all, or the given ids in the given order)."""
    q = select(Product).where(Product.brand_id == brand.id, Product.is_active.is_(True))
    if ids is not None:
        q = q.where(Product.id.in_(ids or [0]))
    rows = [p for p in db.execute(q.order_by(Product.id)).scalars() if not foreign_store_product(brand, p)]
    if ids is not None:
        order = {pid: i for i, pid in enumerate(ids)}
        rows.sort(key=lambda p: order.get(p.id, len(order)))
    return rows


def archive_foreign_products_everywhere(db: Session) -> int:
    """Startup clean-up for rows stored before the website guard existed. Returns how many were archived."""
    return sum(archive_foreign_products(db, b) for b in db.execute(select(Brand)).scalars())


def archive_foreign_products(db: Session, brand: Brand) -> int:
    """Deactivate another store's rows still active on this brand. Returns how many were archived."""
    n = 0
    for p in db.execute(select(Product).where(Product.brand_id == brand.id, Product.is_active.is_(True))).scalars():
        if foreign_store_product(brand, p):
            p.is_active = False
            n += 1
    return n
