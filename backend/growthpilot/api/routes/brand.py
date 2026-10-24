from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import audit
from ...db import get_db
from ...models import Asset, Brand, Persona, Product
from ...services import assets as asset_service
from ...services.errors import WorkflowError
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx, rate_limit

router = APIRouter(prefix="/api", tags=["brand"])

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def current_brand(ctx: Ctx, required: bool = True) -> Brand | None:
    b = ctx.db.execute(select(Brand).where(Brand.workspace_id == ctx.workspace.id).order_by(Brand.id).limit(1)
                       ).scalar_one_or_none()
    if b is None and required:
        raise ApiError(404, "No brand yet. Create one in Brand Brain.", "no_brand")
    return b


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    positioning: str = Field(default="", max_length=3000)
    voice: str = Field(default="", max_length=3000)
    tone: str = Field(default="", max_length=3000)
    audience: str = Field(default="", max_length=3000)
    location: str = Field(default="", max_length=160)
    goals: str = Field(default="", max_length=3000)
    website: str = Field(default="", max_length=255)
    colors: list[str] = Field(default_factory=list, max_length=8)
    visual_guidelines: str = Field(default="", max_length=3000)
    approved_claims: list[str] = Field(default_factory=list, max_length=100)
    restricted_claims: list[str] = Field(default_factory=list, max_length=100)
    prohibited_messaging: list[str] = Field(default_factory=list, max_length=100)
    constraints: str = Field(default="", max_length=3000)
    permitted_sources: list[str] = Field(default_factory=list, max_length=50)


def _clean_list(xs: list[str], limit: int = 300) -> list[str]:
    return [x.strip()[:limit] for x in xs if x and x.strip()]


@router.get("/brand")
def get_brand(ctx: Ctx = Depends(get_ctx)):
    b = current_brand(ctx, required=False)
    if b is None:
        return {"brand": None, "personas": [], "products": []}
    personas = ctx.db.execute(select(Persona).where(Persona.brand_id == b.id)).scalars().all()
    products = ctx.db.execute(select(Product).where(Product.brand_id == b.id).order_by(Product.id)).scalars().all()
    return {"brand": S.brand(b), "personas": [S.persona(p) for p in personas],
            "products": [S.product(p) for p in products]}


@router.put("/brand")
def save_brand(body: BrandIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    if body.website and not body.website.startswith(("http://", "https://")):
        raise ApiError(400, "Website must start with https://", "validation")
    bad = [c for c in body.colors if not HEX.match(c)]
    if bad:
        raise ApiError(400, f"Colours must be hex like #2F3A2F ({', '.join(bad[:3])}).", "validation")
    b = current_brand(ctx, required=False)
    created = b is None
    if created:
        b = Brand(workspace_id=ctx.workspace.id)
        ctx.db.add(b)
    data = body.model_dump()
    for k in ("approved_claims", "restricted_claims", "prohibited_messaging"):
        data[k] = _clean_list(data[k])
    data["permitted_sources"] = _clean_list([s.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
                                             for s in data["permitted_sources"]], 255)
    for k, v in data.items():
        setattr(b, k, v.strip() if isinstance(v, str) else v)
    ctx.db.flush()
    audit.record(ctx.db, "brand.created" if created else "brand.updated", workspace_id=ctx.workspace.id,
                 user_id=ctx.user.id, target_type="brand", target_id=b.id, ip=ctx.ip)
    ctx.db.commit()
    return {"brand": S.brand(b)}


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    goals: str = Field(default="", max_length=2000)
    pain_points: str = Field(default="", max_length=2000)
    preferred_platforms: list[str] = Field(default_factory=list, max_length=10)


@router.post("/brand/personas")
def add_persona(body: PersonaIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    b = current_brand(ctx)
    p = Persona(workspace_id=ctx.workspace.id, brand_id=b.id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.commit()
    return S.persona(p)


@router.put("/brand/personas/{pid}")
def edit_persona(pid: int, body: PersonaIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    p = ctx.get(Persona, pid)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    ctx.db.commit()
    return S.persona(p)


@router.delete("/brand/personas/{pid}")
def delete_persona(pid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    ctx.db.delete(ctx.get(Persona, pid))
    ctx.db.commit()
    return {"ok": True}


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    collection: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=3000)
    price: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    dimensions: str = Field(default="", max_length=160)
    materials: list[str] = Field(default_factory=list, max_length=20)
    finishes: list[str] = Field(default_factory=list, max_length=20)
    verified_attributes: dict[str, str] = Field(default_factory=dict)
    image_asset_id: int | None = None
    is_active: bool = True


def _apply_product(ctx: Ctx, p: Product, body: ProductIn) -> None:
    data = body.model_dump()
    price = data.pop("price")
    if price not in (None, ""):
        try:
            p.price = Decimal(str(price).replace(",", ""))
        except InvalidOperation as exc:
            raise ApiError(400, "Price must be a number.", "validation") from exc
        if p.price < 0:
            raise ApiError(400, "Price can't be negative.", "validation")
    else:
        p.price = None
    if data["image_asset_id"]:
        ctx.get(Asset, data["image_asset_id"])
    if len(data["verified_attributes"]) > 30:
        raise ApiError(400, "Too many verified attributes.", "validation")
    data["materials"] = _clean_list(data["materials"], 120)
    data["finishes"] = _clean_list(data["finishes"], 120)
    data["verified_attributes"] = {k.strip()[:60]: str(v).strip()[:200] for k, v in data["verified_attributes"].items()
                                   if k.strip()}
    data["currency"] = data["currency"].upper()
    for k, v in data.items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)


@router.get("/products")
def list_products(ctx: Ctx = Depends(get_ctx)):
    b = current_brand(ctx, required=False)
    if b is None:
        return []
    rows = ctx.db.execute(select(Product).where(Product.brand_id == b.id).order_by(Product.id)).scalars().all()
    return [S.product(p) for p in rows]


@router.post("/products")
def add_product(body: ProductIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    b = current_brand(ctx)
    p = Product(workspace_id=ctx.workspace.id, brand_id=b.id)
    _apply_product(ctx, p, body)
    ctx.db.add(p)
    try:
        ctx.db.flush()
    except IntegrityError as exc:
        ctx.db.rollback()
        raise ApiError(400, f"SKU {body.sku} already exists.", "exists") from exc
    audit.record(ctx.db, "product.created", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="product", target_id=p.id, ip=ctx.ip)
    ctx.db.commit()
    return S.product(p)


@router.put("/products/{pid}")
def edit_product(pid: int, body: ProductIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    p = ctx.get(Product, pid)
    _apply_product(ctx, p, body)
    try:
        ctx.db.flush()
    except IntegrityError as exc:
        ctx.db.rollback()
        raise ApiError(400, f"SKU {body.sku} already exists.", "exists") from exc
    audit.record(ctx.db, "product.updated", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="product", target_id=p.id, ip=ctx.ip)
    ctx.db.commit()
    return S.product(p)


@router.delete("/products/{pid}")
def delete_product(pid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    p = ctx.get(Product, pid)
    audit.record(ctx.db, "product.deleted", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="product", target_id=p.id, ip=ctx.ip, sku=p.sku)
    ctx.db.delete(p)
    ctx.db.commit()
    return {"ok": True}


# ── assets ───────────────────────────────────────────────────────────────


@router.post("/assets")
async def upload_asset(file: UploadFile = File(...), alt_text: str = Form(""), kind: str = Form("image"),
                       ctx: Ctx = Depends(get_ctx)):
    ctx.require_editor()
    rate_limit(f"upload:{ctx.user.id}", 60, 3600)
    data = await file.read(asset_service.MAX_UPLOAD_BYTES + 1)
    b = current_brand(ctx, required=False)
    try:
        a = asset_service.save_upload(ctx.db, workspace_id=ctx.workspace.id, brand_id=b.id if b else None,
                                      filename=file.filename or "upload", data=data, alt_text=alt_text,
                                      kind="logo" if kind == "logo" else "image")
    except WorkflowError as exc:
        raise ApiError(400, str(exc), "validation") from exc
    audit.record(ctx.db, "asset.uploaded", workspace_id=ctx.workspace.id, user_id=ctx.user.id, target_type="asset",
                 target_id=a.id, ip=ctx.ip, size=a.size_bytes, content_type=a.content_type)
    ctx.db.commit()
    return S.asset(a)


@router.get("/assets")
def list_assets(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(Asset).where(Asset.workspace_id == ctx.workspace.id).order_by(Asset.id.desc())
                          .limit(200)).scalars().all()
    return [S.asset(a) for a in rows]


@router.get("/assets/{aid}/file")
def asset_file(aid: int, ctx: Ctx = Depends(get_ctx)):
    a = ctx.get(Asset, aid)
    path = asset_service.store().path(a.storage_key)
    if not path.exists():
        raise ApiError(404, "File missing.", "not_found")
    headers = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'", "X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=3600"}
    return FileResponse(path, media_type=a.content_type, headers=headers)


@router.get("/public/assets/{token}.{ext}")
def public_asset(token: str, ext: str, db: Session = Depends(get_db)):
    """Unauthenticated, unguessable URL so Instagram can fetch images. Only JPEG/PNG uploads are served."""
    a = db.execute(select(Asset).where(Asset.public_token == token)).scalar_one_or_none()
    if a is None or a.content_type not in asset_service.ALLOWED or asset_service.ALLOWED[a.content_type] != f".{ext}":
        raise ApiError(404, "Not found.", "not_found")
    return FileResponse(asset_service.store().path(a.storage_key), media_type=a.content_type,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=86400"})
