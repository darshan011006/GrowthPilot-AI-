"""Mockable, workspace-scoped Canva poster job processing primitives."""
from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update

from ..agent.briefs import ClaimAllowed, CreativeBrief, to_canva_handoff, validate_brief
from ..config import get_settings
from ..creative.canva_mcp import (
    CanvaMCPError,
    _candidate_rows,
    _nested,
    connected_workspace_client,
    generate_design_args,
    reserve_daily_generation,
    safe_canva_message,
)
from ..models import (
    Asset,
    Brand,
    CanvaPosterJob,
    ContentItem,
    ContentStatus,
    Product,
    utcnow,
)
from . import assets

MAX_JOB_CALLS = 3


def _claim_supported(claim: ClaimAllowed, product: Product | None) -> bool:
    if product is None:
        return False
    try:
        return {
            "name": claim.value == product.name[:160] and claim.text == product.name[:160],
            "category": claim.value == product.category and claim.text == f"Category: {product.category}",
            "materials": claim.value in (product.materials or []) and claim.text == f"Material: {claim.value}",
            "dimensions": claim.value == product.dimensions and claim.text == f"Size: {product.dimensions}",
            "price": (product.price is not None and Decimal(claim.value) == Decimal(product.price)
                      and claim.text == f"Price ₹{product.price:,.0f} (caption only; recheck before posting)"),
        }[claim.field]
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return False


def _schema_args(client, tool: str, values: dict[str, Any]) -> dict[str, Any]:
    schema = client.schema(tool)
    props = schema.get("properties", {})
    args = {k: v for k, v in values.items() if k in props}
    missing = sorted(set(schema.get("required", [])) - set(args))
    if missing:
        raise CanvaMCPError(f"Unmapped required {tool} fields: {', '.join(missing)}")
    return args


def _urls(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _urls(child)
    elif isinstance(value, list):
        for child in value:
            yield from _urls(child)
    elif isinstance(value, str) and value.startswith("https://"):
        yield value


def _select_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer Canva's own numeric quality/relevance score; keep stable API order on ties."""
    if not candidates:
        return None
    scored = [(index, row.get("quality_score", row.get("relevance_score", row.get("score"))))
              for index, row in enumerate(candidates)]
    numeric = [(index, score) for index, score in scored if isinstance(score, (float, int))]
    return candidates[max(numeric, key=lambda pair: pair[1])[0]] if numeric else candidates[0]


def _design_id(payload: dict[str, Any]) -> str | None:
    if isinstance(payload.get("design_id"), str):
        return payload["design_id"]
    if isinstance(payload.get("designId"), str):
        return payload["designId"]
    design = payload.get("design")
    if isinstance(design, dict) and isinstance(design.get("id"), str):
        return design["id"]
    for value in payload.values():
        if isinstance(value, dict) and (found := _design_id(value)):
            return found
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and (found := _design_id(item)):
                    return found
    return None


def _qa_verdict(brief: CreativeBrief, brand: Brand, product: Product | None, *, image_used: bool,
                image_skip_reason: str | None) -> dict[str, Any]:
    """Run deterministic text/product guards; visual checks remain pending human review."""
    unsupported = [claim.text for claim in brief.claims_allowed if not _claim_supported(claim, product)]
    copy = " ".join([brief.headline, brief.tagline, brief.cta]).casefold()
    religious = any(word in copy for word in ("mantra", "sanskrit", "ॐ", "swastika", "deity"))
    product_prices = {str(value) for value in (getattr(product, "price", None), getattr(product, "mrp", None))
                      if value is not None}
    found_prices = [m.group(0).strip() for m in re.finditer(r"(?:₹|Rs\.?\s*)\s?\d+(?:\.\d{1,2})?", copy, re.I)]
    bad_prices = [price for price in found_prices if not any(re.sub(r"\s", "", price).casefold()
                    in re.sub(r"\s", "", allowed).casefold() for allowed in product_prices)]
    required_text_issue = "Required text, brand, and CTA are not OCR-verified in the exported image."
    issues = [required_text_issue, "Export contrast and product-photo match require human visual review."]
    if unsupported:
        issues.append("Claims need review against product facts.")
    if bad_prices:
        issues.append("Price does not exactly match catalogue data.")
    if image_skip_reason:
        issues.append(image_skip_reason)
    if religious or brief.needs_human_review:
        issues.append("Religious imagery/text or brief signal requires human review.")
    issues.append("Religious imagery, symbols, mantra, and Sanskrit screening requires human review.")
    return {"passed": False, "status": "REQUIRES_HUMAN_REVIEW", "issues": issues,
            "checks": {"required_text": "not_verified", "brand": "not_verified", "cta": "not_verified",
                       "claims_supported_by_product_data": not unsupported,
                       "price_accuracy_from_brief": not bad_prices,
                       "product_photo_policy": brief.image_policy == "text_only" or image_used or
                       brief.image_policy == "may_use_images",
                       "visual_review": "pending"},
            "religious_content": religious or brief.needs_human_review,
            "religious_visual_check": "requires_human_review"}


def _persist_poster(db, item: ContentItem, job: CanvaPosterJob, brand: Brand, png: bytes, design_id: str,
                    qa: dict[str, Any], *, image_trust: str, image_skip_reason: str | None,
                    edit_link_available: bool) -> None:
    asset = assets.save_upload(db, workspace_id=job.workspace_id, brand_id=brand.id,
        filename=f"canva-poster-{item.id}-{job.id}.png", data=png, alt_text="Canva poster, awaiting human review.")
    asset.source = "rendered"
    from . import content as content_workflow
    content_workflow.update(db, item, {"asset_id": asset.id}, user_id=None, role="editor", source="canva",
                            note="Attached exported Canva poster for human review.")
    content_workflow._clear_approval(item)
    item.status = ContentStatus.IN_REVIEW
    item.canva_poster = {"job_id": job.id, "design_id": design_id, "asset_id": asset.id,
                         "mode": "image-based" if image_trust == "uploaded" else "text-only",
                         "image_trust": image_trust, "image_skip_reason": image_skip_reason, "qa": qa,
                         "edit_link_available": edit_link_available}
    job.status = "completed"
    job.error = "Poster is stored and awaiting human visual review."


def validate_brief_for_item(db, item: ContentItem, brand: Brand) -> tuple[CreativeBrief, dict[str, Any]]:
    if not item.creative_brief:
        raise CanvaMCPError("Create and save a CreativeBrief before requesting a Canva poster.")
    try:
        brief = validate_brief(item.creative_brief, brand.name)
    except Exception as exc:
        raise CanvaMCPError(f"Stored CreativeBrief failed validation ({type(exc).__name__}).") from None
    if brief.content_id != item.id or brief.platform != item.platform:
        raise CanvaMCPError("CreativeBrief does not match this content item.")
    if brand.workspace_id != item.workspace_id:
        raise CanvaMCPError("Brand is unavailable in this workspace.")
    products = db.execute(select(Product).where(Product.id.in_(item.product_ids or [-1]),
        Product.workspace_id == item.workspace_id, Product.brand_id == brand.id)).scalars().all()
    by_sku = {product.sku: product for product in products}
    for claim in brief.claims_allowed:
        product = by_sku.get(claim.product_sku)
        if product is None:
            raise CanvaMCPError("CreativeBrief claim refers to a product outside this content item.")
        if not _claim_supported(claim, product):
            raise CanvaMCPError("CreativeBrief contains a claim that does not match verified product data.")
    return brief, to_canva_handoff(brief)


async def _upload_trusted_images(client, db, workspace_id: int, brand: Brand, brief: CreativeBrief) -> list[str]:
    ids = []
    for ref in to_canva_handoff(brief).get("image_refs", []):
        asset = db.get(Asset, ref.get("asset_id")) if ref.get("asset_id") else None
        if not asset or asset.workspace_id != workspace_id or asset.brand_id not in (None, brand.id):
            continue
        trust = ref.get("trust", "unknown")
        if asset.source not in {"catalogue", "upload"} or trust not in {"real_match", "uploaded"}:
            continue
        ids.append(await _upload_asset(client, asset, f"Upload verified product photo for {brand.name}."))
    return ids


async def _upload_asset(client, asset: Asset, user_intent: str) -> str:
    data = assets.store().path(asset.storage_key).read_bytes()
    if len(data) > assets.MAX_UPLOAD_BYTES:
        raise CanvaMCPError("Brand or product image exceeds Canva upload limit.")
    schema = client.schema("create-upload-url")
    values = {"filename": asset.filename, "name": asset.filename, "content_type": asset.content_type,
              "mime_type": asset.content_type, "file_size": len(data), "size_bytes": len(data),
              "user_intent": user_intent[:255]}
    args = {k: v for k, v in values.items() if k in schema.get("properties", {})}
    if set(schema.get("required", [])) - set(args):
        raise CanvaMCPError("Canva upload schema has required fields GrowthPilot cannot safely map.")
    result = await client.call("create-upload-url", args)
    upload_url = _nested(result, "upload_url", "uploadUrl")
    media_id = _nested(result, "asset_id", "media_id", "assetId")
    if not isinstance(upload_url, str) or not upload_url.startswith("https://") or not isinstance(media_id, str):
        raise CanvaMCPError("Canva upload response omitted a safe URL or asset id.")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
        response = await http.put(upload_url, content=data, headers={"Content-Type": asset.content_type})
    if response.status_code >= 300:
        raise CanvaMCPError(f"Canva image upload failed with HTTP {response.status_code}.")
    return media_id


async def _upload_brand_logo(client, db, workspace_id: int, brand: Brand) -> str | None:
    if not brand.logo_asset_id or "create-upload-url" not in client.tools:
        return None
    asset = db.get(Asset, brand.logo_asset_id)
    if (asset is None or asset.workspace_id != workspace_id or asset.brand_id not in (None, brand.id)
            or asset.kind != "logo" or asset.content_type not in {"image/png", "image/jpeg"}):
        return None
    return await _upload_asset(client, asset, f"Upload the official {brand.name} brand logo for poster identity.")


def _brand_prompt(query: str, brand: Brand, logo_attached: bool, brief: CreativeBrief,
                  image_skip_reason: str | None = None) -> str:
    if image_skip_reason:
        sentences = re.split(r"(?<=[.!?])\s+", query.strip())
        query = " ".join(sentence for sentence in sentences
                         if not re.search(r"\b(supplied|attached)\s+(?:product\s+)?photo\b", sentence, re.I))
        query += " Text-led layout only; do not depict or redraw a specific product."
    palette = ", ".join(str(color)[:24] for color in (brand.colors or [])[:5]) or "use the brand profile palette"
    tone = (brand.tone or brand.voice or "clear and consistent with the brand profile")[:120]
    identity = (f"Brand identity: show the name \"{brand.name}\" exactly. Tone: {tone}. Palette: {palette}. "
                + ("Use the attached official brand logo without changing it. " if logo_attached
                   else f"No logo file is available; render \"{brand.name}\" as a text wordmark. "))
    allowed = "; ".join(claim.text for claim in brief.claims_allowed)[:500]
    guardrails = "Use no claims beyond the validated brief and product records. Do not invent prices, discounts, "
    guardrails += "materials, origin, health, or quality claims."
    if allowed:
        guardrails += f" Approved product facts: {allowed}."
    return f"{identity}{query.strip()}\n{guardrails}"[:3500]


async def rest_export(db, workspace_id: int, design_id: str, *, client_factory=httpx.AsyncClient,
                      sleep=asyncio.sleep) -> bytes:
    """Development-only token fallback; isolated behind a mockable REST interface."""
    from .canva_rest_dev import export_png
    return await export_png(design_id, client_factory=client_factory, sleep=sleep)


async def process_job(db, job: CanvaPosterJob, *, rest_exporter=rest_export) -> None:
    item = db.get(ContentItem, job.content_id)
    if item is None or item.workspace_id != job.workspace_id:
        raise CanvaMCPError("Content item is unavailable in this workspace.")
    if item.status in {ContentStatus.PUBLISHED, ContentStatus.PUBLISHING, ContentStatus.CANCELLED}:
        raise CanvaMCPError("A poster cannot be attached to content that is already final.")
    brand = db.get(Brand, item.brand_id)
    if brand is None or brand.workspace_id != job.workspace_id:
        raise CanvaMCPError("Brand is unavailable in this workspace.")
    brief, handoff = validate_brief_for_item(db, item, brand)
    product = None
    if item.product_ids:
        product = db.execute(select(Product).where(Product.id.in_(item.product_ids),
            Product.workspace_id == job.workspace_id, Product.brand_id == brand.id)).scalars().first()
    if job.calls_used >= MAX_JOB_CALLS:
        raise CanvaMCPError("Per-job generation call cap reached.")
    settings = get_settings()
    async with connected_workspace_client(db, job.workspace_id, settings) as (client, _credential):
        if not {"generate-design", "create-design-from-candidate"}.issubset(client.tools):
            raise CanvaMCPError("Authenticated Canva MCP is missing required allow-listed tools.")
        cap = getattr(settings, "canva_mcp_daily_cap", 10)
        generate_schema = client.schema("generate-design")
        can_attach_assets = "asset_ids" in generate_schema.get("properties", {})
        if brief.image_policy == "must_use_images" and not can_attach_assets:
            raise CanvaMCPError("Canva generate-design schema cannot accept the required verified image asset.")
        uploaded_ids = await _upload_trusted_images(client, db, job.workspace_id, brand, brief) \
            if brief.image_policy != "text_only" and can_attach_assets and "create-upload-url" in client.tools else []
        logo_id = await _upload_brand_logo(client, db, job.workspace_id, brand) if can_attach_assets else None
        image_trust = "uploaded" if uploaded_ids else "none"
        if brief.image_policy == "must_use_images" and not uploaded_ids:
            raise CanvaMCPError("Required image policy has no verified real-match or uploaded image available.")
        image_skip_reason = None
        if brief.image_policy != "text_only" and not uploaded_ids:
            image_skip_reason = ("The generate-design schema cannot attach product images." if not can_attach_assets
                                 else "No verified product image was attachable; poster was generated text-only.")
        q = handoff.get("canva_query")
        if not q:
            raise CanvaMCPError("CreativeBrief has no Canva query.")
        query = _brand_prompt(q, brand, logo_id is not None, brief, image_skip_reason)
        all_asset_ids = [*uploaded_ids, *([logo_id] if logo_id else [])]
        args = generate_design_args(client.tools["generate-design"], query=query,
            user_intent=f"Create a private {brief.format} draft for human review.", asset_ids=all_asset_ids or None)
        job.calls_used += 1
        reserve_daily_generation(db, limit=cap, now=utcnow())
        db.commit()
        generated = await client.call("generate-design", args, reservation_made=True)
        db.flush()
        generated = await client.poll_design_job(generated)
        candidates = _candidate_rows(generated)
        if not candidates:
            raise CanvaMCPError("Canva returned no design candidates.")
        candidate = _select_candidate(candidates)
        candidate_id = _nested(candidate, "candidate_id", "id")
        if not candidate_id:
            raise CanvaMCPError("Canva candidate omitted its id.")
        committed = await client.call("create-design-from-candidate", _schema_args(client,
            "create-design-from-candidate", {"candidate_id": candidate_id,
            "job_id": _nested(generated, "job_id", "jobId"),
            "user_intent": f"Commit private {brief.format} poster for review."}))
        design_id = _design_id(committed)
        if not isinstance(design_id, str):
            raise CanvaMCPError("Canva commit returned no design id.")
        job.status = "exporting"
        item.canva_poster = {"job_id": job.id, "design_id": design_id, "asset_id": None,
                             "mode": "image-based" if uploaded_ids else "text-only",
                             "image_trust": image_trust, "image_skip_reason": None,
                             "edit_link_available": bool(_nested(committed, "edit_url", "editUrl"))}
        db.commit()
        png = None
        if "export-design" in client.tools:
            try:
                exported = await client.call("export-design", _schema_args(client, "export-design", {
                    "design_id": design_id, "format": "png", "export_format": "png", "as_single_image": True,
                    "user_intent": "Export poster PNG for review."}))
                for url in _urls(exported):
                    if urlparse(url).scheme != "https":
                        continue
                    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as downloader:
                        try:
                            r = await downloader.get(url)
                        except httpx.HTTPError:
                            continue
                    if r.status_code == 200 and r.content.startswith(b"\x89PNG\r\n\x1a\n"):
                        png = r.content
                        break
            except CanvaMCPError:
                # REST export is the only fallback when MCP export is absent or unusable.
                png = None
        if png is None:
            png = await rest_exporter(db, job.workspace_id, design_id)
    if len(png) > assets.MAX_UPLOAD_BYTES:
        raise CanvaMCPError("Exported poster exceeds the supported 8 MB asset limit.")
    qa = _qa_verdict(brief, brand, product, image_used=image_trust == "uploaded",
                     image_skip_reason=image_skip_reason)
    job.status = "qa"
    db.commit()
    _persist_poster(db, item, job, brand, png, design_id, qa,
                    image_trust=image_trust, image_skip_reason=image_skip_reason,
                    edit_link_available=bool(_nested(committed, "edit_url", "editUrl")))


def process_queued(db, *, limit=1):
    jobs = db.execute(select(CanvaPosterJob.id).where(CanvaPosterJob.status == "queued")
                      .order_by(CanvaPosterJob.created_at).limit(limit)).scalars().all()
    processed = 0
    for job_id in jobs:
        claimed = db.execute(update(CanvaPosterJob).where(CanvaPosterJob.id == job_id,
            CanvaPosterJob.status == "queued").values(status="generating"))
        if claimed.rowcount != 1:
            continue
        db.commit()
        job = db.get(CanvaPosterJob, job_id)
        try:
            asyncio.run(process_job(db, job))
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(CanvaPosterJob, job.id)
            if job:
                job.status = "failed"
                job.error = safe_canva_message(str(exc))[:500] or type(exc).__name__
                item = db.get(ContentItem, job.content_id)
                poster = getattr(item, "canva_poster", None) if item else None
                if isinstance(poster, dict) and poster.get("job_id") == job.id:
                    item.canva_poster = {**poster, "error": job.error}
                db.commit()
        processed += 1
    return processed
