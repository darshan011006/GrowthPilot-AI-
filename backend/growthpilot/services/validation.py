"""Deterministic content validation: product claims, brand consistency, platform constraints.

Rules are conservative. A claim passes only when it is backed by the product catalogue or an approved
claim; anything else that *looks like* a factual commercial claim fails or is flagged for review.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Asset, Brand, Competitor, CompetitorObservation, ContentItem, Product, utcnow


@dataclass
class Check:
    code: str
    status: str  # pass | warn | fail
    message: str
    claim: str = ""
    evidence: str = ""


@dataclass
class Report:
    product_claims: list[Check] = field(default_factory=list)
    brand: list[Check] = field(default_factory=list)
    platform: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.product_claims + self.brand + self.platform if c.status == "fail"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.product_claims + self.brand + self.platform if c.status == "warn"]

    def to_dict(self, version: int) -> dict:
        return {
            "version": version, "checked_at": utcnow().isoformat(), "ok": not self.failures,
            "failures": len(self.failures), "warnings": len(self.warnings),
            "product_claims": [asdict(c) for c in self.product_claims],
            "brand": [asdict(c) for c in self.brand],
            "platform": [asdict(c) for c in self.platform],
        }


# ── helpers ──────────────────────────────────────────────────────────────

MATERIALS = [
    "solid wood", "engineered wood", "plywood", "mdf", "particle board", "teak", "sheesham", "acacia", "oak",
    "walnut", "mango wood", "pine", "rubberwood", "bamboo", "rattan", "cane", "jute", "linen", "cotton", "velvet",
    "boucle", "bouclé", "leather", "leatherette", "faux leather", "wool", "silk", "marble", "granite", "quartz",
    "glass", "brass", "steel", "iron", "aluminium", "aluminum", "chrome", "terrazzo", "ceramic", "memory foam",
]
SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")
PRICE_RE = re.compile(r"(?:₹|\brs\.?|\binr)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:/-|rupees)", re.I)
DIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(cm|mm|inches|inch|in\b|ft|feet|\")", re.I)
DISCOUNT_RE = re.compile(r"\d+\s?%\s?off|\bsale\b|\bdiscount|\boffers?\b|\bflat\s?(?:₹|rs)|buy one get|\bbogo\b|"
                         r"cashback|\bdeal\b|\bcoupon", re.I)
WARRANTY_RE = re.compile(r"(\d+)[\s-]*(?:year|yr)s?\b[^.]*?\b(?:warranty|guarantee)|\b(?:warranty|guarantee)\b", re.I)
STOCK_RE = re.compile(r"in stock|ready to ship|ships? (?:in|within) \d+|limited stock|only \d+ left|selling fast|"
                      r"same[- ]day delivery|next[- ]day delivery|free (?:delivery|shipping)|delivered in \d+", re.I)
CERT_RE = re.compile(r"\bcertified\b|\bfsc\b|\biso\s?\d*|greenguard|bifma|\borganic\b|non[- ]toxic|\beco[- ]friendly\b|"
                     r"\bsustainabl[ey]|\brecycled\b|\bzero[- ]waste\b|carbon[- ]neutral", re.I)
SUPERLATIVE_RE = re.compile(r"\bbest\b|\bcheapest\b|#1\b|number one|\bguaranteed\b|\blifetime\b|\bunbreakable\b|"
                            r"\b100%|\bwaterproof\b|\bindestructible\b|\bperfect\b", re.I)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _money(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _covered_by_approved(sentence: str, approved: list[str]) -> str | None:
    s = _norm(sentence)
    for claim in approved:
        c = _norm(claim)
        if c and c in s:
            return claim
    return None


def item_text(item: ContentItem) -> str:
    parts = [item.hook, item.caption, item.cta, " ".join(item.hashtags or [])]
    return "\n".join(p for p in parts if p)


def final_caption(item: ContentItem) -> str:
    """What actually gets posted: hook (if not already in caption) + caption + CTA + hashtags."""
    body = item.caption.strip()
    if item.hook and _norm(item.hook) not in _norm(body):
        body = f"{item.hook.strip()}\n\n{body}"
    if item.cta and _norm(item.cta) not in _norm(body):
        body = f"{body}\n\n{item.cta.strip()}"
    tags = [t for t in (item.hashtags or []) if t.lower() not in body.lower()]
    if tags:
        body = f"{body}\n\n{' '.join(tags)}"
    return body


# ── product claims ───────────────────────────────────────────────────────


def check_product_claims(text: str, brand: Brand, referenced: list[Product], catalogue: list[Product]) -> list[Check]:
    checks: list[Check] = []
    approved = list(brand.approved_claims or [])
    products = referenced or catalogue
    sentences = [s for s in SENTENCE_SPLIT.split(text) if s.strip()]

    # Prices must match a catalogue price exactly.
    known_prices = {p.price: p for p in products if p.price is not None}
    for m in PRICE_RE.finditer(text):
        value = _money(m.group(1) or m.group(2))
        if value is None or value < 100:  # ignore tiny numbers like "2/-" typos
            continue
        if value in known_prices:
            p = known_prices[value]
            checks.append(Check("price", "pass", f"Price matches catalogue ({p.name}).", m.group(0), f"SKU {p.sku}"))
        else:
            checks.append(Check("price", "fail", "Price doesn't match any referenced catalogue price.", m.group(0)))

    for sentence in sentences:
        approved_hit = _covered_by_approved(sentence, approved)
        if DISCOUNT_RE.search(sentence):
            if approved_hit:
                checks.append(Check("offer", "pass", "Offer wording matches an approved claim.", sentence.strip(),
                                    approved_hit))
            else:
                checks.append(Check("offer", "fail", "Mentions a discount/offer that isn't an approved claim.",
                                    sentence.strip()))
        if WARRANTY_RE.search(sentence):
            ok = approved_hit
            if not ok:
                years = re.search(r"(\d+)[\s-]*(?:year|yr)", sentence, re.I)
                for p in products:
                    w = str(p.verified_attributes.get("warranty", "")) if p.verified_attributes else ""
                    if w and years and years.group(1) in w:
                        ok = f"{p.name}: warranty {w}"
                        break
            checks.append(Check("warranty", "pass" if ok else "fail",
                                "Warranty claim verified." if ok else "Warranty claim not backed by catalogue or approved claims.",
                                sentence.strip(), ok or ""))
        if STOCK_RE.search(sentence):
            checks.append(Check("availability", "pass" if approved_hit else "fail",
                                "Delivery/stock wording is an approved claim." if approved_hit else
                                "States stock or delivery terms that aren't approved claims.", sentence.strip(),
                                approved_hit or ""))
        for m in CERT_RE.finditer(sentence):
            word = m.group(0).lower()
            attrs = " ".join(f"{k} {v}" for p in products for k, v in (p.verified_attributes or {}).items()).lower()
            ok = approved_hit or (word in attrs and word)
            checks.append(Check("certification", "pass" if ok else "fail",
                                "Certification/sustainability wording verified." if ok else
                                f"“{m.group(0)}” isn't backed by verified attributes or approved claims.",
                                sentence.strip(), str(ok) if ok else ""))

    # Materials must belong to the referenced products.
    lowered = text.lower()
    ref_mats = {_norm(x) for p in products for x in (p.materials or []) + (p.finishes or [])}
    all_mats = {_norm(x) for p in catalogue for x in (p.materials or []) + (p.finishes or [])}
    for mat in MATERIALS:
        if re.search(rf"\b{re.escape(mat)}\b", lowered):
            if any(mat in m for m in ref_mats):
                checks.append(Check("material", "pass", f"“{mat}” is a listed material/finish.", mat))
            elif any(mat in m for m in all_mats):
                checks.append(Check("material", "warn", f"“{mat}” is used in the catalogue but not in the products "
                                    "this post references.", mat))
            else:
                checks.append(Check("material", "fail", f"“{mat}” isn't a material of any catalogue product.", mat))

    # Dimensions must appear in the referenced products' dimensions.
    dims_text = " ".join(p.dimensions or "" for p in products)
    dim_numbers = set(re.findall(r"\d+(?:\.\d+)?", dims_text))
    for m in DIM_RE.finditer(text):
        num = m.group(1)
        checks.append(Check("dimension", "pass" if num in dim_numbers else "fail",
                            "Dimension matches catalogue." if num in dim_numbers else "Dimension not in catalogue.",
                            m.group(0)))

    # Brand policy lists.
    for phrase in brand.prohibited_messaging or []:
        if phrase.strip() and _norm(phrase) in _norm(text):
            checks.append(Check("prohibited", "fail", "Uses prohibited messaging.", phrase))
    for phrase in brand.restricted_claims or []:
        if phrase.strip() and _norm(phrase) in _norm(text):
            checks.append(Check("restricted", "warn", "Restricted claim: needs evidence and owner sign-off.", phrase))
    for m in SUPERLATIVE_RE.finditer(text):
        if not _covered_by_approved(m.group(0), approved):
            checks.append(Check("superlative", "warn", "Absolute or superlative wording; make sure it's defensible.",
                                m.group(0)))
    if not checks:
        checks.append(Check("no_claims", "pass", "No product or commercial claims detected."))
    return checks


# ── brand consistency ────────────────────────────────────────────────────

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def check_brand(item: ContentItem, brand: Brand, competitor_names: list[str], competitor_excerpts: list[str]) -> list[Check]:
    text = item_text(item)
    checks: list[Check] = []
    if text.count("!") > 3:
        checks.append(Check("tone", "warn", "More than three exclamation marks; may not match the brand voice."))
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", text) if w not in {"DIWALI", "BENGALURU"}]
    if len(caps) > 2:
        checks.append(Check("tone", "warn", f"Several ALL-CAPS words ({', '.join(caps[:4])})."))
    if len(EMOJI_RE.findall(text)) > 6:
        checks.append(Check("tone", "warn", "Heavy emoji use (more than 6)."))
    if not item.cta.strip():
        checks.append(Check("cta", "warn", "No call to action."))
    for name in competitor_names:
        if name and re.search(rf"\b{re.escape(name)}\b", text, re.I):
            checks.append(Check("competitor_mention", "fail", f"Names competitor “{name}”.", name))
    caption = _norm(item.caption)
    for ex in competitor_excerpts:
        e = _norm(ex)
        if len(e) > 40 and len(caption) > 40:
            ratio = difflib.SequenceMatcher(None, caption, e).ratio()
            if ratio > 0.6 or e[:60] in caption:
                checks.append(Check("originality", "fail", "Caption is too similar to observed competitor content.",
                                    ex[:120], f"similarity {ratio:.0%}"))
                break
    if not item.caption.strip():
        checks.append(Check("empty", "fail", "Caption is empty."))
    if re.search(r"\[(ADD|TODO|INSERT|TBD)[^\]]*\]", text, re.I):
        checks.append(Check("placeholder", "fail", "Contains an unfilled placeholder like [ADD …]."))
    if not any(c.status != "pass" for c in checks):
        checks.append(Check("voice", "pass", "No brand-consistency problems detected."))
    return checks


# ── platform constraints ─────────────────────────────────────────────────

IG_CAPTION_MAX = 2200
IG_HASHTAGS_MAX = 30
IG_MENTIONS_MAX = 20
IG_CAROUSEL_MAX = 10


def check_platform(item: ContentItem, assets: list[Asset]) -> list[Check]:
    checks: list[Check] = []
    live = get_settings().is_live
    if item.platform != "instagram":
        checks.append(Check("adapter", "warn", f"No publishing adapter for {item.platform}; plan/export only."))
        return checks
    caption = final_caption(item)
    tags = re.findall(r"(?<!\w)#\w+", caption)
    mentions = re.findall(r"(?<!\w)@\w+", caption)
    checks.append(Check("caption_length", "pass" if len(caption) <= IG_CAPTION_MAX else "fail",
                        f"Caption is {len(caption)}/{IG_CAPTION_MAX} characters."))
    checks.append(Check("hashtags", "pass" if len(tags) <= IG_HASHTAGS_MAX else "fail",
                        f"{len(tags)}/{IG_HASHTAGS_MAX} hashtags."))
    if len(mentions) > IG_MENTIONS_MAX:
        checks.append(Check("mentions", "fail", f"{len(mentions)} @mentions; Instagram allows {IG_MENTIONS_MAX}."))
    if item.content_type in ("reel", "story"):
        checks.append(Check("format", "fail", f"Publishing {item.content_type}s needs video upload, which isn't "
                            "implemented. Keep as a brief or post manually."))
        return checks
    needed = 2 if item.content_type == "carousel" else 1
    if len(assets) < needed:
        checks.append(Check("media", "fail", f"{item.content_type.title()} needs at least {needed} image(s); "
                            f"has {len(assets)}."))
    if item.content_type == "carousel" and len(assets) > IG_CAROUSEL_MAX:
        checks.append(Check("media", "fail", f"Carousels allow up to {IG_CAROUSEL_MAX} images."))
    placeholders = [a for a in assets if a.source == "placeholder"]
    if placeholders:
        n = len(placeholders)
        checks.append(Check("media", "fail" if live else "warn",
                            f"{n} placeholder image(s) — replace with real product photos before publishing." if live
                            else f"{n} placeholder image(s) (demo). Real publishing needs real JPEG photos.",
                            ", ".join(a.filename for a in placeholders)[:300]))
    for a in assets:
        if a.source == "placeholder":
            continue
        if a.content_type != "image/jpeg":
            checks.append(Check("media", "fail" if live else "warn", "Instagram publishing accepts JPEG only.",
                                a.filename))
        if a.width and a.height:
            ratio = a.width / a.height
            ok = 0.8 <= ratio <= 1.91
            checks.append(Check("aspect_ratio", "pass" if ok else "fail",
                                f"Aspect ratio {a.width}×{a.height} ({ratio:.2f}); feed images need 4:5 to 1.91:1.",
                                a.filename))
    return checks


# ── entry point ──────────────────────────────────────────────────────────


def item_assets(db: Session, item: ContentItem) -> list[Asset]:
    ids = ([item.asset_id] if item.asset_id else []) + list(item.slide_asset_ids or [])
    if not ids:
        return []
    rows = {a.id: a for a in db.execute(select(Asset).where(Asset.id.in_(ids),
                                                            Asset.workspace_id == item.workspace_id)).scalars()}
    return [rows[i] for i in ids if i in rows]


def validate_item(db: Session, item: ContentItem) -> Report:
    brand = db.get(Brand, item.brand_id)
    catalogue = list(db.execute(select(Product).where(Product.brand_id == brand.id)).scalars())
    referenced = [p for p in catalogue if p.id in (item.product_ids or [])]
    comps = list(db.execute(select(Competitor).where(Competitor.brand_id == brand.id)).scalars())
    excerpts = [o.excerpt for o in db.execute(
        select(CompetitorObservation).where(CompetitorObservation.workspace_id == item.workspace_id)).scalars()]
    report = Report(
        product_claims=check_product_claims(item_text(item), brand, referenced, catalogue),
        brand=check_brand(item, brand, [c.name for c in comps], excerpts),
        platform=check_platform(item, item_assets(db, item)),
    )
    item.validation = report.to_dict(item.version)
    return report
