"""Render the saved text-only Deepavali brief to a local PNG without network access."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from growthpilot.creative.render import CreativeInput, Palette, render  # noqa: E402
from growthpilot.services.canva_poster_pipeline import _overlay_brand_mark  # noqa: E402


def _logo_path(brand_name: str) -> Path | None:
    folder = ROOT / "data" / "brand-assets"
    if not folder.is_dir():
        return None
    slug = re.sub(r"[^a-z0-9]+", "", brand_name.casefold())
    candidates = [path for path in folder.iterdir() if path.is_file()
                  and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}]
    preferred = [path for path in candidates if "logo" in path.stem.casefold()
                 and (not slug or slug in re.sub(r"[^a-z0-9]+", "", path.stem.casefold()))]
    return sorted(preferred or candidates, key=lambda path: path.name.casefold())[0] if (preferred or candidates) else None


def main() -> None:
    brief_path = ROOT / "docs" / "creative-briefs" / "brief-1.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    if brief.get("image_policy") != "text_only" or brief.get("image_refs"):
        raise SystemExit("Refusing to render: brief is not text-only.")

    required = brief.get("required_text", [])
    headline, tagline, cta = brief.get("headline", ""), brief.get("tagline", ""), brief.get("cta", "")
    if not all(text in required for text in (headline, tagline, cta)):
        raise SystemExit("Refusing to render: required copy is incomplete.")
    brand_names = [text for text in required if text and text != tagline and text in tagline]
    if not brand_names:
        raise SystemExit("Refusing to render: cannot identify the required brand name from the brief.")
    brand_name = min(brand_names, key=len)
    colors = brief.get("style", {}).get("colors", [])

    result = render(CreativeInput(
        template="festive", width=1080, height=1350, headline=headline, subline=tagline, cta=cta,
        brand_name="", palette=Palette.from_colors(colors), photo=None, background=None, logo=None, fmt="PNG",
    ))
    logo_path = _logo_path(brand_name)
    logo_bytes = logo_path.read_bytes() if logo_path else None
    poster_png = _overlay_brand_mark(result.data, brand_name, logo_bytes)

    output = ROOT / "data" / "demo-posters" / "deepavali_brief1.png"
    backup = output.parent / "backup" / output.name
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        backup.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(poster_png)
        shutil.copy2(output, backup)
    except OSError:
        desktop = Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        output = desktop / output.name
        backup = desktop / "backup" / output.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(poster_png)
        shutil.copy2(output, backup)
    print(f"Poster: {output}")
    print(f"Backup: {backup}")
    print(f"Brand mark: {'logo' if logo_bytes else 'text wordmark'}")


if __name__ == "__main__":
    main()
