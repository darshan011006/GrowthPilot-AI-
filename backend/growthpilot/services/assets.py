"""Local asset storage (swap for object storage by replacing ``AssetStore``)."""

from __future__ import annotations

import html
import struct
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Asset
from .errors import WorkflowError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # Instagram's image limit is 8 MB
ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png"}


class AssetStore:
    def __init__(self, root: Path):
        self.root = root

    def save(self, data: bytes, ext: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        key = f"{uuid.uuid4().hex}{ext}"
        (self.root / key).write_bytes(data)
        return key

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise WorkflowError("Invalid asset path.")
        return p

    def delete(self, key: str) -> None:
        try:
            self.path(key).unlink(missing_ok=True)
        except WorkflowError:
            pass


def store() -> AssetStore:
    return AssetStore(get_settings().asset_path)


def sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def image_size(data: bytes, ctype: str) -> tuple[int | None, int | None]:
    try:
        if ctype == "image/png":
            w, h = struct.unpack(">II", data[16:24])
            return w, h
        if ctype == "image/jpeg":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg
    except struct.error:
        pass
    return None, None


def save_upload(db: Session, *, workspace_id: int, brand_id: int | None, filename: str, data: bytes,
                alt_text: str = "", kind: str = "image") -> Asset:
    if len(data) > MAX_UPLOAD_BYTES:
        raise WorkflowError("Images must be 8 MB or smaller.")
    ctype = sniff(data)
    if ctype is None:
        raise WorkflowError("Only JPEG and PNG images are accepted (checked by file content, not name).")
    w, h = image_size(data, ctype)
    key = store().save(data, ALLOWED[ctype])
    safe_name = "".join(ch for ch in Path(filename or "upload").name if ch.isalnum() or ch in "._- ")[:120] or "upload"
    a = Asset(workspace_id=workspace_id, brand_id=brand_id, kind=kind, source="upload", filename=safe_name,
              content_type=ctype, size_bytes=len(data), width=w, height=h, storage_key=key, alt_text=alt_text[:1000])
    db.add(a)
    db.flush()
    return a


def make_placeholder(db: Session, *, workspace_id: int, brand_id: int | None, title: str, brief: str,
                     colors: list[str] | None = None, synthetic: bool = False) -> Asset:
    """A clearly labelled SVG placeholder for an image brief when no image provider/asset exists."""
    bg, fg = (colors or ["#E9E3D8", "#2F3A2F"])[:2] if colors and len(colors) >= 2 else ("#E9E3D8", "#2F3A2F")
    words, lines, line = (brief or title).split(), [], ""
    for w in words:
        if len(line) + len(w) > 46:
            lines.append(line)
            line = ""
        line += (" " if line else "") + w
        if len(lines) >= 6:
            break
    if line and len(lines) < 7:
        lines.append(line)
    tspans = "".join(
        f'<tspan x="60" dy="{0 if i == 0 else 40}">{html.escape(t)}</tspan>' for i, t in enumerate(lines))
    title_lines, cur = [], ""
    for w in title[:90].split():
        if len(cur) + len(w) > 30 and cur:
            title_lines.append(cur)
            cur = ""
        cur += (" " if cur else "") + w
    if cur:
        title_lines.append(cur)
    title_lines = title_lines[:3]
    title_spans = "".join(
        f'<tspan x="60" dy="{0 if i == 0 else 56}">{html.escape(t)}</tspan>' for i, t in enumerate(title_lines))
    body_y = 230 + 56 * (len(title_lines) - 1) + 90
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
<rect width="1080" height="1350" fill="{html.escape(bg)}"/>
<rect x="30" y="30" width="1020" height="1290" fill="none" stroke="{html.escape(fg)}" stroke-width="4" stroke-dasharray="18 12"/>
<text x="60" y="130" font-family="Helvetica, Arial, sans-serif" font-size="34" font-weight="700" fill="#B42318">PLACEHOLDER — NOT A PRODUCT PHOTO</text>
<text x="60" y="230" font-family="Helvetica, Arial, sans-serif" font-size="46" font-weight="700" fill="{html.escape(fg)}">{title_spans}</text>
<text x="60" y="{body_y}" font-family="Helvetica, Arial, sans-serif" font-size="30" fill="{html.escape(fg)}">{tspans}</text>
<text x="60" y="1280" font-family="Helvetica, Arial, sans-serif" font-size="26" fill="{html.escape(fg)}">Image brief generated by GrowthPilot · replace with a real photo</text>
</svg>"""
    key = store().save(svg.encode(), ".svg")
    a = Asset(workspace_id=workspace_id, brand_id=brand_id, kind="image", source="placeholder",
              filename=f"placeholder-{title[:30]}.svg", content_type="image/svg+xml", size_bytes=len(svg),
              width=1080, height=1350, storage_key=key, alt_text=f"Placeholder for: {brief[:200]}",
              is_synthetic=synthetic)
    db.add(a)
    db.flush()
    return a


def public_url(asset: Asset) -> str:
    """Unguessable URL Instagram can fetch. Only meaningful when BASE_URL is publicly reachable over HTTPS."""
    ext = ALLOWED.get(asset.content_type, ".bin")
    return f"{get_settings().base_url.rstrip('/')}/api/public/assets/{asset.public_token}{ext}"
