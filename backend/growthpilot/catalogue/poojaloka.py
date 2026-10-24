"""Poojaloka storefront connector (https://poojaloka.com).

The public storefront at poojaloka.com is a single-page app that reads its catalogue from a public JSON API at
https://api.poojaloka.com/api (the same requests any visitor's browser makes; no login). Endpoints used
(inspected 2026-10-24):

  GET /products?page=N&pageSize=100     → {"products": [...], "total", "page", "pageSize", "totalPages"}
  GET /products/{slug}                  → {"product": {..., "variants", "description", "deliveryAvailable", ...}}
  GET /categories, /festivals, /hero, /articles

Etiquette: identified User-Agent, HTTPS only, SSRF-checked, at most 100 items per page, a pause between pages,
and no authenticated or admin endpoints. api.poojaloka.com has no robots.txt (HTTP 404), so no paths are
disallowed; poojaloka.com/robots.txt returns the app shell rather than robots rules.

Image audit at the time of writing: 2,876 of 2,877 products used generic images from cdn.pixabay.com (stock
photos per category), and one used an upload on billing.poojaloka.com. Stock images are labelled
``stock_photo`` and are never presented as the product.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from ..research.net import BlockedURL, host_of, safe_get
from . import CatalogueError

STOREFRONT = "https://poojaloka.com"
PAGE_SIZE = 100
PAGE_PAUSE_SECONDS = 1.0
_sleep = time.sleep

PRODUCT_PHOTO_HOSTS = {"billing.poojaloka.com"}  # the store's own uploads
STOCK_PHOTO_HOSTS = {"cdn.pixabay.com"}
TEMPLATE_DESCRIPTION = re.compile(r"from Poojaloka's own store inventory", re.I)
# Materials are only recorded when the source's own product name or category states them.
MATERIAL_WORDS = {"brass": "brass", "copper": "copper", "german silver": "german silver", "jerman silver": "german silver",
                  "steel": "steel", "iron": "iron", "wood": "wood", "glass": "glass", "panchaloha": "panchaloha",
                  "panchloha": "panchaloha", "mud": "clay", "marble": "marble", "silver": "silver", "cotton": "cotton",
                  "silk": "silk", "sandal": "sandalwood"}


def materials_from(name: str, category: str) -> list[str]:
    """Materials named in the product name; the category is used only when the name names none."""
    def scan(text: str) -> list[str]:
        text = f" {text} ".lower()
        found: list[str] = []
        for word, mat in MATERIAL_WORDS.items():
            if re.search(rf"\b{re.escape(word)}", text) and mat not in found:
                if mat == "silver" and "german silver" in found:
                    continue
                found.append(mat)
        return found

    return scan(name) or scan(category)


def set_sleep(fn) -> None:
    global _sleep
    _sleep = fn


def _money(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def image_kind(urls: list[str]) -> str:
    if not urls:
        return "none"
    hosts = {host_of(u) for u in urls}
    if hosts & PRODUCT_PHOTO_HOSTS:
        return "product_photo"
    if hosts <= STOCK_PHOTO_HOSTS:
        return "stock_photo"
    return "unverified"


def quality(raw: dict, price: Decimal | None, mrp: Decimal | None, kind: str) -> list[dict]:
    q = []
    stock = raw.get("stock")
    if price is None:
        q.append({"code": "no_price", "message": "No price at the source."})
    elif price <= 1:
        q.append({"code": "price_suspicious", "message": f"Price ₹{price} looks like a data-entry error; don't "
                  "promote until confirmed."})
    if mrp is not None and price is not None and mrp > price:
        q.append({"code": "mrp_above_price", "message": f"Source shows MRP ₹{mrp} above the price ₹{price}. Any "
                  "discount wording still needs an approved claim and fresh data."})
    if isinstance(stock, int) and stock < 0:
        q.append({"code": "stock_negative", "message": f"Stock is {stock} (negative) at the source."})
    elif stock == 0:
        q.append({"code": "out_of_stock", "message": "Stock is 0 at the source" + (
            " (back-orders allowed)." if raw.get("allowBackorder") else ".")})
    if kind == "stock_photo":
        q.append({"code": "no_product_photo", "message": "Only a generic stock image is listed; it is not a photo "
                  "of this product and won't be used as one."})
    elif kind == "unverified":
        q.append({"code": "photo_unverified", "message": "Image host isn't recognised as the store's own uploads."})
    elif kind == "none":
        q.append({"code": "no_image", "message": "No image listed."})
    desc = raw.get("description") or ""
    if desc and TEMPLATE_DESCRIPTION.search(desc):
        q.append({"code": "description_template", "message": "Description is a generic template, not product "
                  "detail; don't quote it as a product claim."})
    if raw.get("deliveryAvailable") is False and raw.get("estDeliveryDays"):
        q.append({"code": "delivery_conflict", "message": "Source says delivery is unavailable but also lists an "
                  f"estimate of {raw.get('estDeliveryDays')} day(s); avoid delivery promises."})
    name = (raw.get("name") or "").strip()
    if name and name == name.lower() and len(name.split()) == 1:
        q.append({"code": "possible_test_listing", "message": f"“{name}” looks like a placeholder or test listing."})
    return q


def normalise(raw: dict) -> dict:
    """Map one storefront product to Product fields. Only facts present at the source are kept."""
    slug = raw.get("slug") or raw.get("id")
    price, mrp = _money(raw.get("price")), _money(raw.get("mrp"))
    urls = [u for u in raw.get("images") or [] if isinstance(u, str) and u.startswith("https://")]
    kind = image_kind(urls)
    cat = raw.get("category") or {}
    variants = [{"label": v.get("label"), "price": float(v["price"]) if v.get("price") is not None else None,
                 "stock": v.get("stock")} for v in raw.get("variants") or []]
    flags = {k: True for k, src in (("best_seller", "isBestSeller"), ("devotee_favorite", "isDevoteeFavorite"))
             if raw.get(src)}
    if raw.get("festival"):
        flags["festival"] = raw["festival"] if isinstance(raw["festival"], str) else json.dumps(raw["festival"])[:120]
    delivery = {}
    if "deliveryAvailable" in raw:
        delivery = {"available": raw.get("deliveryAvailable"), "est_days": raw.get("estDeliveryDays")}
    desc = (raw.get("description") or "").strip()
    return {
        "sku": str(slug)[:64], "source_ref": str(slug), "name": (raw.get("name") or str(slug)).strip()[:160],
        "name_local": (raw.get("nameKn") or "")[:255], "category": (cat.get("name") or "Uncategorised")[:80],
        "collection": "", "description": desc[:3000], "price": price, "mrp": mrp, "currency": "INR",
        "stock": raw.get("stock") if isinstance(raw.get("stock"), int) else None,
        "allow_backorder": raw.get("allowBackorder"), "variants": variants, "image_urls": urls[:10],
        "image_kind": kind, "flags": flags, "delivery": delivery,
        "source_url": f"{STOREFRONT}/product/{slug}",
        "data_quality": quality(raw, price, mrp, kind),
        "materials": materials_from(raw.get("name") or "", cat.get("name") or ""),
        "verified_attributes": {"material_source": "product name/category at the source"}
        if materials_from(raw.get("name") or "", cat.get("name") or "") else {},
        **({"_retrieved_at": raw["_retrieved_at"]} if raw.get("_retrieved_at") else {}),
    }


class PoojalokaStore:
    kind = "poojaloka_store_api"

    def __init__(self, base_url: str = "https://api.poojaloka.com/api"):
        self.base = base_url.rstrip("/")
        self.label = f"Poojaloka storefront API ({host_of(self.base)})"
        self.allowed = [host_of(self.base)]

    def _get(self, path: str) -> dict:
        url = urljoin(self.base + "/", path.lstrip("/"))
        try:
            resp = safe_get(url, allowed_domains=self.allowed, max_bytes=5_000_000,
                            headers={"Accept": "application/json"})
        except BlockedURL as exc:
            raise CatalogueError(f"Request blocked: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise CatalogueError(f"Couldn't reach the Poojaloka API ({type(exc).__name__}).", retryable=True) from exc
        if resp.status_code == 404:
            return {}
        if resp.status_code >= 400:
            raise CatalogueError(f"Poojaloka API returned HTTP {resp.status_code} for {path}.",
                                 retryable=resp.status_code >= 500 or resp.status_code == 429)
        try:
            return resp.json()
        except ValueError as exc:
            raise CatalogueError(f"Poojaloka API returned non-JSON for {path}.") from exc

    def list_products(self, *, limit: int | None = None) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            data = self._get(f"products?page={page}&pageSize={PAGE_SIZE}")
            rows = data.get("products") or []
            out += [normalise(r) for r in rows]
            if limit and len(out) >= limit:
                return out[:limit]
            if page >= int(data.get("totalPages") or 1) or not rows:
                return out
            page += 1
            _sleep(PAGE_PAUSE_SECONDS)

    def get_product(self, ref: str) -> dict | None:
        data = self._get(f"products/{ref}")
        raw = data.get("product")
        return normalise(raw) if raw else None

    def brand_content(self) -> dict:
        out = {}
        for key, path in (("hero", "hero"), ("festivals", "festivals"), ("articles", "articles"),
                          ("categories", "categories")):
            try:
                data = self._get(path)
            except CatalogueError:
                continue
            out[key] = data.get(key, data) if isinstance(data, dict) else data
        return out


class SnapshotSource:
    """The bundled, dated snapshot (backend/growthpilot/demo/poojaloka_snapshot.json)."""

    kind = "poojaloka_snapshot"

    def __init__(self, snapshot: dict):
        self.snap = snapshot
        self.label = f"Poojaloka snapshot retrieved {snapshot['meta']['retrieved_at'][:10]} (not live)"

    def list_products(self, *, limit: int | None = None) -> list[dict]:
        rows = [normalise(dict(r)) for r in self.snap["products"]]
        return rows[:limit] if limit else rows

    def get_product(self, ref: str) -> dict | None:
        raw = next((r for r in self.snap["products"] if r.get("slug") == ref), None)
        return normalise(dict(raw)) if raw else None

    def brand_content(self) -> dict:
        return {k: self.snap.get(k) for k in ("hero", "festivals", "articles", "categories")}
