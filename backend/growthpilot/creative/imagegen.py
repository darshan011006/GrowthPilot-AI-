"""Optional AI backgrounds via Gemini image generation (Interactions API, ``response_format`` type ``image``).

Only abstract backgrounds are requested — never products, people, deities or text — and the poster labels the
background as AI-generated. Product imagery always comes from real photos. Implemented from Google's image
generation docs (checked 2026-10-24); tested against a mocked API only.
"""

from __future__ import annotations

import base64

import httpx

from .. import usage
from ..config import get_settings
from ..research.net import client

API = "https://generativelanguage.googleapis.com/v1beta/interactions"
RATIOS = {(4, 5): "4:5", (1, 1): "1:1", (2, 3): "2:3", (16, 9): "16:9", (9, 16): "9:16", (3, 4): "3:4"}


class ImageGenError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def nearest_ratio(w: int, h: int) -> str:
    r = w / h
    return min(RATIOS.items(), key=lambda kv: abs(kv[0][0] / kv[0][1] - r))[1]


def background_prompt(theme: str, colors: list[str]) -> str:
    return (f"An abstract, softly lit decorative background for a festive Indian home-devotion brand poster. Theme: "
            f"{theme[:120]}. Use a palette close to {', '.join(colors[:4]) or 'maroon, gold and cream'}. Subtle "
            "texture, warm bokeh, traditional geometric patterns at the edges, generous empty space in the centre "
            "for text. No text, no letters, no logos, no products, no people, no deities, no religious idols.")


def generate_background(theme: str, colors: list[str], width: int, height: int) -> tuple[bytes, str, dict]:
    s = get_settings()
    if not s.image_generation_configured:
        raise ImageGenError("No image-generation provider is configured (IMAGE_GENERATION_PROVIDER=gemini and a key).")
    if s.is_demo:
        raise ImageGenError("Demo mode makes no external calls; using the template background.")
    model = s.image_generation_model
    usage.preflight(usage.unit_cost(model), "An AI background image")
    prompt = background_prompt(theme, colors)
    body = {"model": model, "store": False, "input": [{"type": "text", "text": prompt}],
            "response_format": {"type": "image", "mime_type": "image/jpeg",
                                "aspect_ratio": nearest_ratio(width, height)}}
    try:
        with client(timeout=httpx.Timeout(120.0, connect=10.0),
                    headers={"x-goog-api-key": s.image_key, "Content-Type": "application/json"}) as c:
            resp = c.post(API, json=body)
    except httpx.HTTPError as exc:
        raise ImageGenError(f"Image request failed ({type(exc).__name__}).", retryable=True) from exc
    if resp.status_code in (401, 403):
        raise ImageGenError("The image provider rejected the API key.")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ImageGenError(f"Image provider busy (HTTP {resp.status_code}).", retryable=True)
    if resp.status_code >= 400:
        raise ImageGenError(f"Image provider returned HTTP {resp.status_code}.")
    data = resp.json()
    for step in data.get("steps") or []:
        for block in step.get("content") or []:
            if block.get("type") == "image" and block.get("data"):
                img = base64.b64decode(block["data"])
                usage.record(provider="gemini-image", operation="background", model=model, units=1,
                             cost_usd=usage.unit_cost(model))
                return img, block.get("mime_type", "image/jpeg"), {"model": model, "prompt": prompt}
    raise ImageGenError("The image provider returned no image.")
