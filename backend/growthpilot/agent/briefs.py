"""create_content_brief rules: one typed, validated ``CreativeBrief`` per planned post.

This module is pure logic (no database access) so every rule can be tested with mocked data. The
``create_content_brief`` tool gathers the facts (``BriefFacts``), plans the weekly mix, and calls
``brief_with_retry`` for each post.

Rules enforced here:
* Weekly mix: per block of five posts, two text-only, two image-based and one combination, but only where a
  trusted image exists. Stock photos are never used as product photos.
* Image policy: ``must_use_images`` only for a real store photo of the product (``real_match``) or a team upload
  linked to the post; unknown trust → ``may_use_images`` and human review; otherwise ``text_only``.
* Claims come only from product data (traceable to a SKU and field). No prices on the poster, no offers.
* Festivals only from a dated, verified calendar, upcoming or ongoing within 21 days of the post.
* No deity imagery, mantras or Sanskrit text; related concepts are flagged and kept out of the prompt.
* No repeats of angle, headline, tagline, layout or palette from the last N posts when an alternative exists.
* Prior QA feedback shapes the brief. One retry; then a flagged text-only evergreen brief.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION = "1.0"
FESTIVAL_WINDOW_DAYS = 21
DEFAULT_REPEAT_WINDOW = 8
HEADLINE_MAX_WORDS = 8
HEADLINE_MAX_WORDS_QA = 5  # after layout/text-fit QA failures
TAGLINE_MAX_WORDS = 14
CTA_MAX_WORDS = 6
QUERY_MAX_WORDS = 120
# One block of the weekly mix (repeats for longer plans): 2 text-only, 2 image-based, 1 combination.
MIX_PATTERN = ("text_only", "image", "combination", "text_only", "image")

Angle = Literal["festival_prep", "product_spotlight", "material_focus", "category_edit", "know_how",
                "brand_promise"]
Policy = Literal["text_only", "may_use_images", "must_use_images"]
Composition = Literal["typographic", "photo_led", "photo_plus_text"]

LAYOUTS: dict[str, dict[str, str]] = {
    "typographic": {
        "centered_stack": "centred stack: headline, tagline, CTA, wordmark at the foot",
        "left_column": "left-aligned column with generous right margin",
        "top_banner": "solid colour band at the top holding the headline, tagline below",
        "framed_border": "thin decorative border frame around centred text",
        "oversized_headline": "oversized headline filling the top half, small tagline beneath",
        "diagonal_band": "diagonal colour band behind the headline",
        "minimal_corner": "headline in the upper-left corner, wordmark lower-right, lots of space",
        "split_blocks": "two stacked colour blocks: headline above, tagline and CTA below",
    },
    "photo_led": {
        "photo_top_text_bottom": "supplied photo in the top two-thirds, text panel below",
        "photo_left_text_right": "supplied photo on the left half, text on the right",
        "photo_framed_center": "supplied photo centred in a frame, text above and below",
        "photo_full_bleed_bar": "supplied photo full-bleed with a solid text bar at the bottom",
    },
    "photo_plus_text": {
        "text_panel_photo_inset": "large text panel with the supplied photo as a smaller inset",
        "split_text_photo": "text on the left two-thirds, supplied photo in a right column",
        "photo_corner_card": "typographic card with the supplied photo in one corner",
    },
}
SIMPLE_LAYOUTS = {"centered_stack", "left_column", "photo_top_text_bottom", "text_panel_photo_inset"}

# Religious concepts: excluded from the prompt and flagged for human review.
DEITY_RE = re.compile(
    r"\b(krishna|rama|ram|lakshmi|laxmi|ganesh\w*|ganapati|vinayak\w*|shiva|siva|vishnu|durga|hanuman|saraswati|"
    r"parvati|murugan|subramany\w*|venkatesh\w*|balaji|ayyappa|kali|devi|goddess(?:es)?|gods?|lord|deity|deities|"
    r"idols?|murti|moorti|vigraha|avatar)\b", re.I)
MANTRA_RE = re.compile(r"\b(mantras?|shlokas?|slokas?|stotram?|chant(?:s|ing)?|japa|gayatri|om|sanskrit)\b|ॐ", re.I)
SCRIPT_RE = re.compile(r"[ऀ-ॿ]")  # Devanagari (Sanskrit text)
RITUAL_REVIEW_RE = re.compile(r"\b(vidhi|abhishek\w*|aarti|arati|homa|havan|sankalpa|prasad\w*)\b", re.I)
OFFER_RE = re.compile(r"\d+\s?%|\boff\b|\bsale\b|\bdiscount\w*|\boffers?\b|\bdeals?\b|\bcoupon\w*|\bcashback\b|"
                      r"buy one|\bbogo\b|\bfree\b|₹|\brs\.?\s?\d|\bprice\w*\b", re.I)
MULTI_CTA_RE = re.compile(r"\s(?:and|or)\s|[&;|/]|[.!?]\s+\S", re.I)
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Fixed prompt sentences. They name prohibited concepts on purpose, so the religious-term scan skips them.
P_EXACT_TEXT = "Use exactly the quoted text and add no other words, numbers, prices, offers or claims."
P_TEXT_ONLY = "Typographic only: no product photos, stock photos, deities, religious figures, mantras or Sanskrit text."
P_IMAGE = "No deities, religious figures, mantras or Sanskrit text; add no other photos."
P_MUST = "Place the supplied photo (asset {aid}) unaltered: no edits, filters, cut-outs or generated additions."
P_MAY = ("The supplied photo (asset {aid}) may be placed unaltered only if a reviewer confirms it is genuine; "
         "otherwise make the design typographic.")
FIXED_SENTENCES = (P_EXACT_TEXT, P_TEXT_ONLY, P_IMAGE)

BASE_BANNED = [
    "prices, MRP, discounts, offers, sale or coupon wording",
    "stock, delivery or availability promises",
    "purity, origin, authenticity, health or spiritual-benefit claims",
    "deity imagery, religious figures, mantras or Sanskrit text",
    "stock photos presented as the product",
    "competitor names, text, layouts or imagery",
    "any text other than required_text",
]


def words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def religious_terms(text: str) -> list[str]:
    """Deity, mantra and Sanskrit terms in ``text`` (excluded from prompts)."""
    found = [m.group(0) for m in DEITY_RE.finditer(text or "")] + [m.group(0) for m in MANTRA_RE.finditer(text or "")]
    if SCRIPT_RE.search(text or ""):
        found.append("Devanagari script")
    return sorted({f.lower() for f in found})


def ritual_terms(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in RITUAL_REVIEW_RE.finditer(text or "")})


# ── schema ───────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImageRef(_Strict):
    source: Literal["brand_site", "uploaded"]
    asset_id: int = Field(gt=0)
    product_sku: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _sku(self) -> ImageRef:
        if self.source == "brand_site" and not self.product_sku:
            raise ValueError("a brand_site image must name the product_sku it shows")
        return self


class FestivalRef(_Strict):
    name: str = Field(min_length=1, max_length=80)
    start: date
    end: date
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _order(self) -> FestivalRef:
        if self.end < self.start:
            raise ValueError("festival end is before its start")
        return self


class ClaimAllowed(_Strict):
    text: str = Field(min_length=1, max_length=160)
    product_sku: str = Field(min_length=1, max_length=64)
    field: Literal["name", "category", "materials", "dimensions", "price"]
    value: str = Field(min_length=1, max_length=160)


class Style(_Strict):
    composition: Composition
    layout: str
    palette: str = Field(min_length=1, max_length=40)
    colors: list[str] = Field(min_length=2, max_length=5)
    mood: str = Field(min_length=1, max_length=120)

    @field_validator("colors")
    @classmethod
    def _hex(cls, v: list[str]) -> list[str]:
        if not all(HEX_RE.match(c) for c in v):
            raise ValueError("colours must be #RRGGBB")
        return v

    @model_validator(mode="after")
    def _layout(self) -> Style:
        if self.layout not in LAYOUTS[self.composition]:
            raise ValueError(f"layout {self.layout!r} doesn't fit composition {self.composition!r}")
        return self


class Signals(_Strict):
    trend_ids: list[int] = Field(default_factory=list, max_length=10)
    competitor_insight_ids: list[int] = Field(default_factory=list, max_length=10)
    reason: str = Field(min_length=1, max_length=400)


class DataIssue(_Strict):
    code: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=400)
    needs_review: bool = False


class CreativeBrief(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    content_id: int = Field(gt=0)
    platform: str = Field(min_length=1, max_length=20)
    format: Literal["single_image", "carousel"]
    objective: str = Field(min_length=1, max_length=300)
    audience: str = Field(min_length=1, max_length=300)
    festival: FestivalRef | None
    angle: Angle
    image_policy: Policy
    image_refs: list[ImageRef] = Field(max_length=3)
    headline: str = Field(min_length=1, max_length=80)
    tagline: str = Field(min_length=1, max_length=140)
    cta: str = Field(min_length=1, max_length=40)
    required_text: list[str] = Field(min_length=2, max_length=6)
    claims_allowed: list[ClaimAllowed] = Field(max_length=10)
    banned: list[str] = Field(min_length=1, max_length=30)
    style: Style
    needs_human_review: bool
    canva_query: str = Field(min_length=1, max_length=1200)
    signals: Signals
    data_issues: list[DataIssue] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _rules(self) -> CreativeBrief:
        errs = structural_errors(self, None)
        if errs:
            raise ValueError("; ".join(errs))
        return self


def structural_errors(b: CreativeBrief, brand_word: str | None = "Poojaloka") -> list[str]:
    """Rules that need only the brief itself. ``brand_word=None`` skips the brand-name rule (the schema
    validator doesn't know the brand; ``validate_brief`` and ``check_brief`` apply it)."""
    e = []
    if words(b.headline) > HEADLINE_MAX_WORDS:
        e.append(f"headline has {words(b.headline)} words (max {HEADLINE_MAX_WORDS})")
    if words(b.tagline) > TAGLINE_MAX_WORDS:
        e.append(f"tagline has {words(b.tagline)} words (max {TAGLINE_MAX_WORDS})")
    if words(b.cta) > CTA_MAX_WORDS or MULTI_CTA_RE.search(b.cta):
        e.append("CTA must be one short call to action")
    if brand_word and brand_word not in b.required_text:
        e.append(f"required_text must include {brand_word!r}")
    for t in (b.headline, b.tagline, b.cta):
        if t not in b.required_text:
            e.append(f"required_text must include {t!r}")
    if brand_word and brand_word not in b.canva_query:
        e.append(f"canva_query must name {brand_word}")
    for t in b.required_text:
        if f'"{t}"' not in b.canva_query:
            e.append(f"canva_query must quote {t!r} exactly")
    if words(b.canva_query) > QUERY_MAX_WORDS:
        e.append(f"canva_query has {words(b.canva_query)} words (max {QUERY_MAX_WORDS})")
    if P_EXACT_TEXT not in b.canva_query:
        e.append("canva_query must prohibit extra text and unsupported claims")
    if b.image_policy == "text_only":
        if b.image_refs:
            e.append("text_only briefs can't reference images")
        if P_TEXT_ONLY not in b.canva_query:
            e.append("text_only canva_query must prohibit product photos, deities, mantras and Sanskrit text")
        if b.style.composition != "typographic":
            e.append("text_only briefs use a typographic composition")
    else:
        if not b.image_refs:
            e.append(f"{b.image_policy} needs at least one image reference")
        if b.style.composition == "typographic":
            e.append("image briefs need a photo composition")
        if b.image_policy == "must_use_images" and "unaltered" not in b.canva_query:
            e.append("canva_query must require the real photo to stay unaltered")
    for t in (b.headline, b.tagline, b.cta):
        if religious_terms(t):
            e.append(f"religious terms in on-image text: {', '.join(religious_terms(t))}")
    if any(i.needs_review for i in b.data_issues) and not b.needs_human_review:
        e.append("needs_human_review must be true when an issue needs review")
    return e


def validate_brief(data: dict | str, brand_word: str = "Poojaloka") -> CreativeBrief:
    """Strictly load a saved or exported brief (schema plus the brand-name rule)."""
    b = CreativeBrief.model_validate_json(data) if isinstance(data, str) else CreativeBrief.model_validate(data)
    errs = structural_errors(b, brand_word)
    if errs:
        raise ValueError("; ".join(errs))
    return b


# ── facts the tool gathers ───────────────────────────────────────────────


@dataclass
class ProductFacts:
    sku: str
    name: str
    category: str
    materials: list[str] = field(default_factory=list)
    dimensions: str = ""
    price: Decimal | None = None
    price_ok: bool = False  # fresh data and no price-quality flags
    promotable: bool = True
    religious: bool = False
    trust: str = "none"  # real_match | stock | unknown | none
    photo_asset_id: int | None = None


@dataclass
class ImageOption:
    source: str  # brand_site | uploaded
    asset_id: int
    trust: str  # real_match | uploaded | unknown
    product_sku: str | None = None


@dataclass
class RecentPost:
    headline: str = ""
    tagline: str = ""
    angle: str | None = None
    layout: str | None = None
    palette: str | None = None


@dataclass
class QA:
    short_headline: bool = False
    high_contrast: bool = False
    simple_layout: bool = False
    drop_price: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class BriefFacts:
    content_id: int
    platform: str
    platform_label: str
    content_type: str
    size: tuple[int, int, str]  # width, height, label
    link_in_caption: bool
    post_date: date
    today: date
    pillar: str
    pillar_kind: str  # guide | know_how | offer | showcase
    brand_name: str
    objective: str
    audience: str
    voice: str = ""
    colors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    product: ProductFacts | None = None
    images: list[ImageOption] = field(default_factory=list)
    festivals: list[dict] = field(default_factory=list)  # verified: name, start, end, source
    unverified_festivals: list[dict] = field(default_factory=list)  # name, hint, note
    undated_festivals: list[str] = field(default_factory=list)
    festival_names: list[str] = field(default_factory=list)  # every known name, dated or not
    wants_festival: bool = False
    article: dict | None = None
    trend_ids: list[int] = field(default_factory=list)
    competitor_ids: list[int] = field(default_factory=list)
    competitor_names: list[str] = field(default_factory=list)
    analytics_note: str = ""
    recent: list[RecentPost] = field(default_factory=list)  # newest first, already cut to the window
    qa: QA = field(default_factory=QA)
    prohibited: list[str] = field(default_factory=list)
    restricted: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)  # gathered while collecting facts
    claim_checker: Callable[[str], list[str]] | None = None  # returns failure messages (catalogue rules)
    is_synthetic: bool = False


# ── festivals ────────────────────────────────────────────────────────────


def parse_day(v) -> date | None:
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def festival_for(f: BriefFacts) -> dict | None:
    """The nearest verified festival that is upcoming or ongoing within the window of the post date."""
    best = None
    for fest in f.festivals:
        start, end = parse_day(fest.get("start")), parse_day(fest.get("end")) or parse_day(fest.get("start"))
        if start is None or end is None or end < f.today or end < f.post_date:
            continue  # past festivals are never used
        if (start - f.post_date).days > FESTIVAL_WINDOW_DAYS:
            continue
        if best is None or start < best["start"]:
            best = {"name": fest["name"], "start": start, "end": end, "source": fest.get("source") or "calendar"}
    return best


# ── choosing ─────────────────────────────────────────────────────────────


def lru(options: list[str], used_newest_first: list[str | None]) -> tuple[str, bool]:
    """First option not used recently; else the one used longest ago. Returns (choice, repeated)."""
    used = [u for u in used_newest_first if u]
    for o in options:
        if o not in used:
            return o, False
    return max(options, key=lambda o: used.index(o)), True


def _lum(hex_: str) -> float:
    def ch(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def palettes(colors: list[str], min_contrast: float = 4.5) -> list[tuple[str, list[str]]]:
    """Background/text/accent triples from the brand colours with readable text contrast."""
    cols = list(dict.fromkeys(c.upper() for c in colors if HEX_RE.match(c or ""))) or ["#FBF3E7", "#2B1810",
                                                                                      "#C99A3D"]
    out = []
    for bg in cols:
        for fg in cols:
            if fg == bg or contrast(bg, fg) < min_contrast:
                continue
            accent = next((c for c in cols if c not in (bg, fg)), fg)
            out.append((f"{bg[1:]}-{fg[1:]}-{accent[1:]}".lower(), [bg, fg, accent]))
    return out or [("fbf3e7-2b1810-c99a3d", ["#FBF3E7", "#2B1810", "#C99A3D"])]


PACK_RE = re.compile(r"[\d.,]+[a-z]{0,3}|pkts?|pcs?|nos?|packs?|gms?|kg|ml", re.I)
DANGLING = {"size", "of", "with", "for", "and", "the", "a", "in", "set", "-", "–", "|", "&"}


def short_name(name: str, max_words: int = 5) -> str:
    """Product name short enough for a headline, never cut mid-phrase (e.g. "… Petti Size")."""
    name = re.sub(r"\s*[\(\[].*?[\)\]]", "", name or "").strip(" -–|,")
    name = name.split("/")[0].strip() or name  # "Camphor/Gede Karpura 40 1 Pkt" → "Camphor"
    parts = name.split()[:max_words]
    while len(parts) > 1 and (parts[-1].lower() in DANGLING or PACK_RE.fullmatch(parts[-1])):
        parts.pop()
    return " ".join(parts)


def angle_options(f: BriefFacts, role: str, festival: dict | None) -> list[str]:
    p = f.product if f.product and f.product.promotable and not f.product.religious else None
    opts: list[str] = []
    if festival and f.pillar_kind in ("guide", "offer"):
        opts.append("festival_prep")
    if f.pillar_kind == "know_how" and f.article and role == "text_only":
        opts.append("know_how")
    if p:
        if role != "text_only" and p.materials:
            opts.append("material_focus")
        opts.append("product_spotlight")
        if p.materials:
            opts.append("material_focus")
    if p and not DEITY_RE.search(p.category):
        opts.append("category_edit")
    if f.pillar_kind == "guide" and f.article and role == "text_only":
        opts.append("know_how")
    if festival:
        opts.append("festival_prep")
    opts.append("brand_promise")
    return list(dict.fromkeys(opts))


def _festival_word(festival: dict | None) -> tuple[str, bool]:
    if not festival:
        return "", False
    if religious_terms(festival["name"]):
        return "the festival", True
    return festival["name"], False


def copy_options(f: BriefFacts, angle: str, festival: dict | None) -> list[tuple[str, str]]:
    """(headline, tagline) candidates for an angle, using verified data only."""
    brand = f.brand_name
    p = f.product
    name = short_name(p.name) if p else ""
    cat = (p.category if p else "") or "pooja essentials"
    fest, _ = _festival_word(festival)
    if angle == "product_spotlight":
        return [(f"Meet our {name}", f"From the {cat} range at {brand}"),
                (f"Spotlight: {name}", f"See its details in the {cat} range at {brand}"),
                (f"{name}, for your pooja shelf", f"Find it in the {cat} range at {brand}")]
    if angle == "material_focus":
        m = (p.materials[0] if p and p.materials else "brass").lower()
        return [(f"{m.title()} for your pooja space", f"Our {name}, from the {cat} range at {brand}"),
                (f"The {m} edit", f"Explore {m} pieces in the {cat} range at {brand}")]
    if angle == "category_edit":
        return [(f"Browse our {cat} range", f"{cat} for every day and festive days, at {brand}"),
                (f"Your {cat} edit", f"Everyday {cat} picks, all at {brand}")]
    if angle == "festival_prep":
        return [(f"Getting ready for {fest}", f"Plan your {fest} pooja list with {brand}"),
                (f"{fest[:1].upper() + fest[1:]} prep, made simple", f"Start your {fest} checklist with {brand}")]
    if angle == "know_how":
        title = str((f.article or {}).get("title") or "")
        out = []
        if title and words(title) <= HEADLINE_MAX_WORDS and not religious_terms(title) and not ritual_terms(title):
            out.append((title, f"Read the full guide from {brand}"))
        return out + [("Pooja know-how, made simple", f"Short, practical guides from {brand}"),
                      ("Small steps for a calm pooja", f"Practical notes from the {brand} team")]
    cats = [c for c in f.categories if not religious_terms(c)][:2]
    first = f"Shop {cats[0].lower()} and more at {brand}" if cats else f"Find everyday essentials at {brand}"
    if len(cats) > 1:
        first = f"Shop {cats[0].lower()}, {cats[1].lower()} and more at {brand}"
    return [("Pooja essentials for every day", first),
            ("Your pooja space, simplified", f"Everyday essentials, thoughtfully listed at {brand}"),
            ("Ready for today's pooja", f"Find everyday essentials at {brand}")]


def cta_for(f: BriefFacts, angle: str) -> str:
    link = "poojaloka.com" if f.brand_name == "Poojaloka" else "our website"
    if angle in ("product_spotlight", "material_focus"):
        return f"View it on {link}" if f.link_in_caption else "Tap the link in bio"
    return {"category_edit": "Browse the range", "festival_prep": "Start your list today",
            "know_how": "Save this guide"}.get(angle, f"Explore {link}" if f.link_in_caption else "Visit the link in bio")


def claims_for(f: BriefFacts, angle: str, allow_price: bool) -> list[ClaimAllowed]:
    p = f.product
    if not p or not p.promotable or p.religious or angle in ("brand_promise", "know_how", "festival_prep"):
        return []
    out = [ClaimAllowed(text=p.name[:160], product_sku=p.sku, field="name", value=p.name[:160])]
    if p.category:
        out.append(ClaimAllowed(text=f"Category: {p.category}", product_sku=p.sku, field="category", value=p.category))
    for m in p.materials[:2]:
        out.append(ClaimAllowed(text=f"Material: {m}", product_sku=p.sku, field="materials", value=m))
    if p.dimensions:
        out.append(ClaimAllowed(text=f"Size: {p.dimensions}", product_sku=p.sku, field="dimensions",
                                value=p.dimensions))
    if allow_price and p.price is not None and p.price_ok:
        out.append(ClaimAllowed(text=f"Price ₹{p.price:,.0f} (caption only; recheck before posting)",
                                product_sku=p.sku, field="price", value=str(p.price)))
    return out


def _query(f: BriefFacts, b_policy: str, composition: str, layout: str, colors: list[str], mood: str,
           required: list[str], refs: list[ImageRef]) -> str:
    full = _query_parts(f, b_policy, composition, layout, colors, mood, required, refs, compact=False)
    if words(full) <= QUERY_MAX_WORDS:
        return full
    return _query_parts(f, b_policy, composition, layout, colors, mood, required, refs, compact=True)


def _query_parts(f: BriefFacts, b_policy: str, composition: str, layout: str, colors: list[str], mood: str,
                 required: list[str], refs: list[ImageRef], *, compact: bool) -> str:
    w, h, label = f.size
    kind = "carousel cover" if f.content_type == "carousel" else "post"
    quoted = ", ".join(f'"{t}"' for t in required)
    parts = [f"Design a {w}×{h} ({label}) {f.platform_label} {kind} for {f.brand_name}.",
             f"Layout: {layout.replace('_', ' ') if compact else LAYOUTS[composition][layout]}.",
             f"Colours {', '.join(colors)}" + ("." if compact else f"; mood: {mood}."),
             f"Text, exactly as written: {quoted}.", P_EXACT_TEXT]
    if b_policy == "text_only":
        parts.append(P_TEXT_ONLY)
    else:
        aid = refs[0].asset_id
        parts.append((P_MUST if b_policy == "must_use_images" else P_MAY).format(aid=aid))
        parts.append(P_IMAGE)
    return " ".join(parts)


def _issue(code: str, message: str, review: bool = False) -> DataIssue:
    return DataIssue(code=code[:40], message=message[:400], needs_review=review)


def build_brief(f: BriefFacts, role: str, attempt: int = 0) -> CreativeBrief:
    """Compose a brief for one post. ``role`` is the planned mix slot: text_only | image | combination."""
    issues = [DataIssue(**i) for i in f.issues]
    festival = festival_for(f)
    if f.wants_festival and festival is None:
        detail = []
        if f.undated_festivals:
            detail.append("no date in the brand's festival calendar for " + ", ".join(f.undated_festivals))
        for u in f.unverified_festivals:
            detail.append(f"{u['name']}: built-in planning calendar says {u['hint']} but marks it unconfirmed")
        issues.append(_issue("festival_date_missing", "No verified festival date within "
                             f"{FESTIVAL_WINDOW_DAYS} days, so this is an evergreen post"
                             + (f" ({'; '.join(detail)})" if detail else "") + "."))
    fest_word, fest_religious = _festival_word(festival)
    if fest_religious:
        issues.append(_issue("religious_concept", f"Festival name “{festival['name']}” names a deity; it is kept "
                             "out of the design prompt.", review=True))

    # Image policy from the planned role and the trust of the images actually available.
    trusted = [o for o in f.images if o.trust in ("real_match", "uploaded")]
    unknown = [o for o in f.images if o.trust == "unknown"]
    refs: list[ImageRef] = []
    policy: str = "text_only"
    if role in ("image", "combination"):
        pick = trusted[:1] or unknown[:1]
        if pick:
            o = pick[0]
            refs = [ImageRef(source=o.source, asset_id=o.asset_id, product_sku=o.product_sku)]
            policy = "must_use_images" if trusted else "may_use_images"
            if not trusted:
                issues.append(_issue("photo_trust_missing", f"Image asset {o.asset_id} has no trust metadata (not "
                                     "confirmed as a real store photo or a team upload); a person must confirm it "
                                     "before it is used.", review=True))
        else:
            issues.append(_issue("mix_downgraded", f"Planned as {role.replace('_', ' ')}, but no trusted image is "
                                 "available for this post, so it is text-only."))
    composition = {"text_only": "typographic"}.get(policy) or ("photo_plus_text" if role == "combination"
                                                               else "photo_led")

    # Angle, then copy; avoid repeats from recent posts where an alternative exists.
    opts = angle_options(f, role if policy != "text_only" else "text_only", festival)
    if policy != "text_only" and refs[0].source == "brand_site":
        opts = [o for o in opts if o in ("product_spotlight", "material_focus", "category_edit")] or opts
    rotated = opts[attempt % len(opts):] + opts[:attempt % len(opts)] if attempt else opts
    angle, angle_repeat = lru(rotated, [r.angle for r in f.recent])
    if festival and angle != "festival_prep":
        festival = None  # only attach a festival the copy is actually about
    if angle_repeat:
        issues.append(_issue("repeat_unavoidable", f"Every supported angle was used in the last {len(f.recent)} "
                             f"posts; reusing the least recent ({angle})."))
    if angle in ("know_how",) and f.article:
        art_terms = religious_terms(f"{f.article.get('title', '')} {f.article.get('excerpt', '')}") + \
            ritual_terms(f"{f.article.get('title', '')} {f.article.get('excerpt', '')}")
        if art_terms:
            issues.append(_issue("religious_concept", "The source guide mentions " + ", ".join(art_terms[:5])
                                 + "; those are kept out of the design prompt and need human review.", review=True))

    recent_heads = {norm(r.headline) for r in f.recent if r.headline}
    recent_tags = {norm(r.tagline) for r in f.recent if r.tagline}
    max_head = HEADLINE_MAX_WORDS_QA if f.qa.short_headline else HEADLINE_MAX_WORDS
    candidates = copy_options(f, angle, festival)
    usable = [(h, t) for h, t in candidates if words(h) <= max_head and words(t) <= TAGLINE_MAX_WORDS
              and norm(h) not in recent_heads and norm(t) not in recent_tags]
    pool = usable or candidates
    headline, tagline = pool[(attempt if attempt and len(pool) > 1 else 0) % len(pool)]
    cta = cta_for(f, angle)
    required = list(dict.fromkeys([headline, tagline, cta, f.brand_name]))

    # Style.
    layouts = list(LAYOUTS[composition])
    if f.qa.simple_layout:
        layouts = [x for x in layouts if x in SIMPLE_LAYOUTS] or layouts
    start = f.content_id % len(layouts)
    layout, _ = lru(layouts[start:] + layouts[:start], [r.layout for r in f.recent])
    pals = palettes(f.colors, 7.0 if f.qa.high_contrast else 4.5)
    pstart = f.content_id % len(pals)
    palette, _ = lru([p[0] for p in pals[pstart:] + pals[:pstart]], [r.palette for r in f.recent])
    colors = dict(pals)[palette]
    mood = "warm, respectful and uncluttered" + ("; high contrast" if f.qa.high_contrast else "")

    claims = claims_for(f, angle, allow_price=attempt == 0 and not f.qa.drop_price)
    banned = list(dict.fromkeys(BASE_BANNED + [f"“{x}”" for x in f.prohibited] +
                                [f"“{x}” (restricted: needs owner sign-off)" for x in f.restricted]))[:30]
    query = _query(f, policy, composition, layout, colors, mood, required, refs)

    reason_bits = [f"{role.replace('_', ' ')} slot in the weekly mix", f"angle {angle.replace('_', ' ')}"]
    if f.trend_ids:
        reason_bits.append(f"{len(f.trend_ids)} supporting research signal(s)")
    if f.competitor_ids:
        reason_bits.append(f"general {f.content_type} pattern seen in {len(f.competitor_ids)} competitor "
                           "reference(s), not copied")
    if f.analytics_note:
        reason_bits.append(f.analytics_note)
    if f.qa.notes:
        reason_bits.append("applies prior QA: " + "; ".join(f.qa.notes[:3]))
    if f.is_synthetic:
        reason_bits.append("demo data")
    reason = "; ".join(reason_bits)[:400]

    issues = list({(i.code, i.message): i for i in issues}.values())[:20]
    return CreativeBrief(
        content_id=f.content_id, platform=f.platform,
        format="carousel" if f.content_type == "carousel" else "single_image",
        objective=f.objective[:300] or "Grow engagement", audience=f.audience[:300] or "Brand audience",
        festival=FestivalRef(**festival) if festival else None, angle=angle, image_policy=policy, image_refs=refs,
        headline=headline, tagline=tagline, cta=cta, required_text=required, claims_allowed=claims, banned=banned,
        style=Style(composition=composition, layout=layout, palette=palette, colors=colors, mood=mood),
        needs_human_review=any(i.needs_review for i in issues), canva_query=query,
        signals=Signals(trend_ids=f.trend_ids[:10], competitor_insight_ids=f.competitor_ids[:10], reason=reason),
        data_issues=issues)


# ── checks that need the facts ───────────────────────────────────────────


def check_brief(b: CreativeBrief, f: BriefFacts) -> list[str]:
    """Context rules: claims traceable to product data, trusted images, verified festivals, no repeats,
    no religious terms or competitor names in the prompt, no unsupported offers or catalogue-rule failures."""
    e = list(structural_errors(b, f.brand_name))
    p = f.product
    for c in b.claims_allowed:
        if not p or c.product_sku != p.sku:
            e.append(f"claim “{c.text}” isn't from this post's product")
            continue
        if c.field == "price":
            try:
                ok = p.price is not None and p.price_ok and Decimal(c.value) == Decimal(p.price)
            except ArithmeticError:
                ok = False
        else:
            ok = {"name": c.value == p.name[:160], "category": c.value == p.category,
                  "materials": c.value in p.materials, "dimensions": c.value == p.dimensions}[c.field]
        if not ok:
            e.append(f"claim “{c.text}” doesn't match the product's {c.field}")
    trust = {o.asset_id: o for o in f.images}
    for r in b.image_refs:
        o = trust.get(r.asset_id)
        if o is None or o.source != r.source:
            e.append(f"image asset {r.asset_id} isn't a real photo or upload linked to this post")
        elif b.image_policy == "must_use_images" and o.trust not in ("real_match", "uploaded"):
            e.append(f"must_use_images needs a real_match or uploaded photo; asset {r.asset_id} is {o.trust}")
    if b.festival:
        ok = any(x["name"] == b.festival.name and parse_day(x.get("start")) == b.festival.start for x in f.festivals)
        if not ok:
            e.append("festival date isn't from the verified calendar")
        if b.festival.end < f.today or b.festival.end < f.post_date:
            e.append("festival is in the past")
        if (b.festival.start - f.post_date).days > FESTIVAL_WINDOW_DAYS:
            e.append(f"festival is more than {FESTIVAL_WINDOW_DAYS} days after the post")
    text = f"{b.headline}\n{b.tagline}\n{b.cta}"
    if b.festival is None:
        for name in f.festival_names:
            for part in re.split(r"\s*/\s*", name):
                if len(part) > 3 and re.search(rf"\b{re.escape(part)}\b", text, re.I):
                    e.append(f"names {part} without a verified date")
    if OFFER_RE.search(text):
        e.append("on-image text mentions a price or offer; none is verified")
    prompt = b.canva_query
    for s in FIXED_SENTENCES:
        prompt = prompt.replace(s, " ")
    if religious_terms(prompt) or ritual_terms(prompt):
        e.append("canva_query contains religious terms: " + ", ".join(religious_terms(prompt) + ritual_terms(prompt)))
    for name in f.competitor_names:
        if name and re.search(rf"\b{re.escape(name)}\b", f"{text}\n{b.canva_query}\n{b.signals.reason}", re.I):
            e.append("brief mentions a competitor by name")
    for phrase in f.prohibited:
        if phrase and phrase.lower() in text.lower():
            e.append(f"uses prohibited messaging “{phrase}”")
    recent_heads = {norm(r.headline) for r in f.recent if r.headline}
    recent_tags = {norm(r.tagline) for r in f.recent if r.tagline}
    if norm(b.headline) in recent_heads:
        e.append("headline repeats a recent post")
    if norm(b.tagline) in recent_tags:
        e.append("tagline repeats a recent post")
    if f.qa.short_headline and words(b.headline) > HEADLINE_MAX_WORDS_QA:
        e.append(f"prior QA asks for a headline of at most {HEADLINE_MAX_WORDS_QA} words")
    if f.claim_checker:
        e += [f"catalogue check: {m}" for m in f.claim_checker(text)]
    return e


def fallback_brief(f: BriefFacts, errors: list[str]) -> CreativeBrief:
    """Flagged, text-only evergreen brief used when a brief fails validation twice."""
    g = BriefFacts(**{**f.__dict__, "product": None, "images": [], "festivals": [], "wants_festival": False,
                      "article": None, "issues": [], "recent": f.recent})
    b = build_brief(g, "text_only", attempt=0)
    issues = list(f.issues) + [{"code": "validation_failed", "message": "Brief failed validation twice ("
                                       + "; ".join(errors)[:300] + "); replaced with a text-only evergreen brief.",
                                       "needs_review": True}]
    data = b.model_dump() | {"needs_human_review": True,
                             "data_issues": [DataIssue(**i).model_dump() for i in issues][:20]}
    return CreativeBrief.model_validate(data)


@dataclass
class BriefOutcome:
    brief: CreativeBrief
    attempts: list[list[str]]  # validation errors of each failed attempt, in order
    fallback: bool


def brief_with_retry(f: BriefFacts, role: str) -> BriefOutcome:
    """Build and validate; retry once with a different approach; else a flagged text-only evergreen brief."""
    failed: list[list[str]] = []
    for attempt in (0, 1):
        try:
            b = build_brief(f, role, attempt)
            errors = check_brief(b, f)
        except ValidationError as exc:
            errors = [str(x.get("msg", ""))[:200] for x in exc.errors()]
        if not errors:
            if attempt:
                data = b.model_dump()
                data["data_issues"] = (data["data_issues"] + [{"code": "validation_retry", "message": "First draft "
                                       "failed validation (" + "; ".join(failed[0])[:250] + ") and was redone.",
                                       "needs_review": False}])[:20]
                b = CreativeBrief.model_validate(data)
            return BriefOutcome(b, failed, False)
        failed.append(errors)
    return BriefOutcome(fallback_brief(f, failed[-1]), failed, True)


# ── weekly mix ───────────────────────────────────────────────────────────


def plan_mix(slots: list[tuple[int, str, str]]) -> tuple[dict[int, str], list[str]]:
    """Assign mix roles. ``slots`` = [(content_id, content_type, image_capability)] in date order, where the
    capability is trusted | unknown | none. Returns ({content_id: role}, shortfall notes)."""
    n = len(slots)
    wanted = [MIX_PATTERN[i % len(MIX_PATTERN)] for i in range(n)]
    need_combo = wanted.count("combination")
    need_image = wanted.count("image")
    roles: dict[int, str] = {}
    rank = {"trusted": 0, "unknown": 1}
    capable = sorted([s for s in slots if s[2] in rank], key=lambda s: (rank[s[2]], slots.index(s)))
    # Combination prefers a carousel, image posts prefer single posts.
    combo = sorted(capable, key=lambda s: (rank[s[2]], s[1] != "carousel", slots.index(s)))[:need_combo]
    for s in combo:
        roles[s[0]] = "combination"
    rest = [s for s in capable if s[0] not in roles]
    for s in sorted(rest, key=lambda s: (rank[s[2]], s[1] == "carousel", slots.index(s)))[:need_image]:
        roles[s[0]] = "image"
    for s in slots:
        roles.setdefault(s[0], "text_only")
    notes = []
    got_image = sum(1 for r in roles.values() if r == "image")
    got_combo = sum(1 for r in roles.values() if r == "combination")
    if got_image < need_image or got_combo < need_combo:
        notes.append(f"Planned {need_image} image-based and {need_combo} combination post(s) but only "
                     f"{got_image + got_combo} post(s) have a trusted or reviewable image; the rest are text-only.")
    return roles, notes


def summary_line(b: CreativeBrief) -> str:
    fest = f", festival {b.festival.name} {b.festival.start:%d %b}" if b.festival else ""
    return (f"#{b.content_id} {b.platform} {b.format} · {b.image_policy} · {b.angle}{fest} · “{b.headline}”"
            + (" · needs review" if b.needs_human_review else ""))


def image_brief_text(b: CreativeBrief) -> str:
    """Plain-text image brief kept on the content item, consistent with the typed brief."""
    img = {"text_only": "Typographic design, no photos.",
           "must_use_images": f"Use the real photo (asset {b.image_refs[0].asset_id if b.image_refs else '-'}) "
                              "unaltered.",
           "may_use_images": "Photo only if a reviewer confirms it is genuine; otherwise typographic."}[b.image_policy]
    return (f"{img} Layout: {b.style.layout.replace('_', ' ')}; colours {', '.join(b.style.colors)}. "
            f"Text: {' / '.join(b.required_text)}.")
