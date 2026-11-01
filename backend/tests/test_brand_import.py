from __future__ import annotations

import httpx

from growthpilot.research import net

from .conftest import Api, make_client

HOME = """<html><head><title>Lumen Candles | Hand-poured soy candles</title>
<meta name="description" content="Lumen Candles makes small-batch soy candles in Pune.">
<meta name="theme-color" content="#a3552b">
<script type="application/ld+json">{"@type":"Organization","name":"Lumen Candles","description":"Small-batch soy candles."}</script>
</head><body><h1>Slow-burn candles</h1><a href="/products/amber">Amber</a></body></html>"""
PRODUCT = """<html><head><title>Amber Candle</title>
<meta name="description" content="A 200g amber candle with a cotton wick.">
<script type="application/ld+json">{"@type":"Product","name":"Amber Candle","sku":"A1","description":"A 200g amber candle with a cotton wick.",
"image":["https://lumen.example/img/amber.jpg"],"offers":{"@type":"Offer","price":"499","priceCurrency":"INR"}}</script>
</head><body><h1>Amber Candle</h1></body></html>"""


def _site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    body = PRODUCT if request.url.path.startswith("/products/") else HOME
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


def _api(monkeypatch, tmp_path) -> Api:
    api = Api(make_client(monkeypatch, tmp_path, "live"))
    api.register()
    assert api.put("/api/brand", {"name": "Lumen"}).status_code == 200
    return api


def test_website_scan_keeps_brand_description_separate_from_products(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    net.set_transport(httpx.MockTransport(_site))
    net.set_resolver(lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    r = api.post("/api/onboarding/scan-website", {"website": "https://lumen.example"})
    assert r.status_code == 200, r.text
    draft = r.json()["draft"]
    assert "soy candles" in draft["description"] and "cotton wick" not in draft["description"]
    assert any(p["name"] == "Amber Candle" for p in draft["products"])
    assert "#a3552b" in [c.lower() for c in draft["colors"]]


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\x9a\x8a\x00\x00\x00\x00IEND\xaeB`\x82")


def _cdn(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})


def test_csv_rows_import_with_cdn_photos(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    net.set_transport(httpx.MockTransport(_cdn))
    net.set_resolver(lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    # What the Brand Brain page posts for a CSV row: store site as source_url, photos on another host (CDN).
    rows = [{"name": "Amber Candle", "sku": "A1", "category": "Candles", "description": "200g amber candle.",
             "price": "499", "currency": "INR", "source_url": "https://lumen.example/",
             "image_urls": ["https://cdn.shopify.example/amber.png"]},
            {"name": "No Site Candle", "sku": "A2", "price": "10", "source_url": "",
             "image_urls": ["https://cdn.shopify.example/b.png"]}]
    r = api.post("/api/onboarding/import-products", {"website": "https://lumen.example", "products": rows})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] == 2, out
    assert out["photos_downloaded"] == 2, out
    products = api.get("/api/products").json()
    items = products if isinstance(products, list) else products.get("products", [])
    assert {p["name"] for p in items} == {"Amber Candle", "No Site Candle"}


def test_profile_sources_limit_is_what_the_import_page_must_respect(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    src = [{"field": "name", "source_url": "https://lumen.example", "retrieved_at": "", "note": f"n{i}"} for i in range(101)]
    r = api.put("/api/brand", {"name": "Lumen", "profile_sources": src})
    assert r.status_code == 422
    assert api.put("/api/brand", {"name": "Lumen", "profile_sources": src[:100]}).status_code == 200


def test_instagram_account_posts_include_posts_made_outside_growthpilot(monkeypatch, tmp_path):
    from growthpilot.db import session_scope
    from growthpilot.models import ChannelConnection, Workspace
    from growthpilot.security import encrypt_json
    from sqlalchemy import select

    api = _api(monkeypatch, tmp_path)
    assert api.get("/api/analytics/instagram-account").json()["connected"] is False
    with session_scope() as db:
        ws = db.execute(select(Workspace)).scalars().first()
        db.add(ChannelConnection(workspace_id=ws.id, adapter="instagram", platform="instagram", name="IG",
                                 account_id="17841", account_label="@lumen", status="connected",
                                 credentials_enc=encrypt_json({"access_token": "t", "login_type": "unified_login"})))

    def graph(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media"):
            return httpx.Response(200, json={"data": [
                {"id": "m1", "timestamp": "2026-10-30T10:00:00+0000", "media_type": "IMAGE", "like_count": 10, "comments_count": 2},
                {"id": "m2", "timestamp": "2026-10-29T10:00:00+0000", "media_type": "VIDEO", "like_count": 5, "comments_count": 1}]})
        if path.endswith("/m1/insights"):
            return httpx.Response(200, json={"data": [{"name": "reach", "values": [{"value": 100}]},
                {"name": "shares", "values": [{"value": 3}]}, {"name": "saved", "values": [{"value": 5}]}]})
        return httpx.Response(400, json={"error": {"message": "no insights", "code": 100}})

    net.set_transport(httpx.MockTransport(graph))
    net.set_resolver(lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    out = api.get("/api/analytics/instagram-account").json()
    assert out["connected"] and out["error"] is None and len(out["posts"]) == 2
    first = next(p for p in out["posts"] if p["id"] == "m1")
    assert first["interactions"] == 10 + 2 + 3 + 5 and first["engagement_rate"] == 0.2
    assert next(p for p in out["posts"] if p["id"] == "m2")["engagement_rate"] is None  # no insights → no rate
