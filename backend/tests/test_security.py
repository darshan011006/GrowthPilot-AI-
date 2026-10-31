from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from growthpilot.api import deps
from growthpilot.api.deps import ApiError, require_json_origin
from growthpilot.config import AppEnv
from growthpilot.research import net
from growthpilot.security import redact

from .conftest import PASSWORD, Api, make_client


def tiny_jpeg(w: int, h: int) -> bytes:
    """Minimal byte string with a JPEG SOI + SOF0 header (enough for type and size sniffing)."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"


def test_unauthenticated_and_csrf(demo):
    r = demo.c.post("/api/brand", json={"name": "x"})
    assert r.status_code in (403, 405)
    r = demo.c.put("/api/brand", json={"name": "x"})  # no CSRF header
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = demo.c.put("/api/brand", json={"name": "x"}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    assert demo.put("/api/brand", json={"name": "Brand"}).status_code == 200
    demo.post("/api/auth/logout")
    assert demo.c.get("/api/overview").status_code == 401


def test_login_requires_json_and_header(demo):
    r = demo.c.post("/api/auth/login", data={"email": "owner@example.com", "password": PASSWORD})
    assert r.status_code == 403
    r = demo.c.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert r.status_code == 403  # missing X-Requested-With


def test_tunnel_origin_is_allowed_only_in_development(monkeypatch):
    def request_for(origin: str) -> Request:
        headers = [(b"origin", origin.encode()), (b"content-type", b"application/json"),
                   (b"x-requested-with", b"GrowthPilot")]
        return Request({"type": "http", "method": "POST", "path": "/api/auth/login", "headers": headers,
                        "query_string": b"", "server": ("backend", 8000), "client": ("127.0.0.1", 1234),
                        "scheme": "http", "http_version": "1.1"})

    monkeypatch.setenv("GROWTHPILOT_TUNNEL_HOST", "sample-tunnel.example")
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(
        app_env=AppEnv.DEVELOPMENT, base_url="http://localhost:3000"))
    require_json_origin(request_for("https://sample-tunnel.example"))
    require_json_origin(request_for("http://127.0.0.1:3000"))
    with pytest.raises(ApiError):
        require_json_origin(request_for("https://another-tunnel.example"))

    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(
        app_env=AppEnv.PRODUCTION, base_url="https://growthpilot.example"))
    with pytest.raises(ApiError) as blocked:
        require_json_origin(request_for("https://sample-tunnel.example"))
    assert blocked.value.status_code == 403


def test_registration_is_invite_only_after_first_user(demo):
    demo.post("/api/auth/logout")
    r = demo.c.post("/api/auth/register", json={"name": "Eve", "email": "eve@example.com", "password": PASSWORD},
                    headers={"X-Requested-With": "GrowthPilot"})
    assert r.status_code == 403


def test_password_policy_and_login_rate_limit(monkeypatch, tmp_path):
    api = Api(make_client(monkeypatch, tmp_path))
    r = api.c.post("/api/auth/register", json={"name": "A", "email": "a@example.com", "password": "short"},
                   headers={"X-Requested-With": "GrowthPilot"})
    assert r.status_code == 400
    api.register(email="a@example.com")
    api.post("/api/auth/logout")
    codes = [api.login("a@example.com", "Wrong-pass-123").status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


def test_tenant_isolation(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    a = Api(client)
    a.register(email="a@example.com")
    a.post("/api/demo/reset", json={"confirm": "RESET"})
    content_id = a.get("/api/content").json()[0]["id"]
    product_id = a.get("/api/products").json()[0]["id"]
    link = a.post("/api/settings/invites", json={"email": "b@example.com", "role": "owner"}).json()["link"]
    # A second, separate workspace: create directly to simulate another tenant.
    from growthpilot.db import session_scope
    from growthpilot.models import Membership, Role, User, Workspace
    from growthpilot.security import hash_password

    with session_scope() as db:
        u = User(email="c@example.com", name="C", password_hash=hash_password(PASSWORD))
        ws = Workspace(name="Other")
        db.add_all([u, ws])
        db.flush()
        db.add(Membership(user_id=u.id, workspace_id=ws.id, role=Role.OWNER))
    a.post("/api/auth/logout")
    c = Api(client)
    assert c.login("c@example.com").status_code == 200
    assert c.get(f"/api/content/{content_id}").status_code == 404
    assert c.put(f"/api/products/{product_id}", json={"sku": "x", "name": "x", "category": "x"}).status_code == 404
    assert c.get("/api/content").json() == []
    assert c.get("/api/products").json() == []
    _ = link


def test_secrets_never_returned(monkeypatch, tmp_path):
    api = Api(make_client(monkeypatch, tmp_path, "live"))
    api.register()
    net.set_resolver(lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", 443))])
    r = api.post("/api/connections/webhook", json={"name": "Hook", "url": "https://hooks.example.com/abc"})
    assert r.status_code == 200
    secret = r.json()["signing_secret"]
    listing = api.get("/api/integrations").text
    assert secret not in listing and "credentials" not in listing
    assert "x" * 48 not in listing  # SECRET_KEY


def test_redaction():
    text = 'error: {"access_token": "IGQVJ123abc", "client_secret":"s3cr3t"} Bearer abc.def sk-ant-api03-XYZ'
    out = redact(text)
    for s in ("IGQVJ123abc", "s3cr3t", "abc.def", "sk-ant-api03-XYZ"):
        assert s not in out


@pytest.mark.parametrize("url", ["http://example.com/", "https://user:pw@example.com/", "https://example.com:8443/",
                                 "ftp://example.com/", "https://localhost/", "https://10.0.0.5/",
                                 "https://169.254.169.254/latest/meta-data/"])
def test_ssrf_guard_blocks(url):
    def resolver(host, port, proto=0):
        ip = {"localhost": "127.0.0.1", "10.0.0.5": "10.0.0.5", "169.254.169.254": "169.254.169.254"}.get(host, "93.184.216.34")
        return [(2, 1, 6, "", (ip, port))]

    net.set_resolver(resolver)
    with pytest.raises(net.BlockedURL):
        net.check_url(url)


def test_domain_allow_list():
    net.set_resolver(lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", 443))])
    net.check_url("https://www.example.com/page", allowed_domains=["example.com"])
    with pytest.raises(net.BlockedURL):
        net.check_url("https://evil.com/", allowed_domains=["example.com"])


def test_upload_validation_and_public_assets(demo_seeded):
    api = demo_seeded
    r = api.c.post("/api/assets", files={"file": ("x.jpg", b"<svg onload=alert(1)>", "image/jpeg")},
                   headers={"X-CSRF-Token": api.csrf})
    assert r.status_code == 400
    r = api.c.post("/api/assets", files={"file": ("x.jpg", b"\xff\xd8\xff" + b"0" * (9 * 1024 * 1024), "image/jpeg")},
                   headers={"X-CSRF-Token": api.csrf})
    assert r.status_code == 400
    r = api.c.post("/api/assets", files={"file": ("../../etc/p.jpg", tiny_jpeg(1080, 1080), "image/jpeg")},
                   headers={"X-CSRF-Token": api.csrf})
    assert r.status_code == 200
    a = r.json()
    assert a["width"] == 1080 and a["height"] == 1080 and "/" not in a["filename"]
    from growthpilot.db import session_scope
    from growthpilot.models import Asset
    from growthpilot.services.assets import make_placeholder

    with session_scope() as db:
        token = db.get(Asset, a["id"]).public_token
        svg = db.query(Asset).filter(Asset.source == "placeholder").first() or make_placeholder(
            db, workspace_id=db.get(Asset, a["id"]).workspace_id, brand_id=None, title="x", brief="y")
        svg_token = svg.public_token
    assert api.c.get(f"/api/public/assets/{token}.jpg").status_code == 200
    assert api.c.get(f"/api/public/assets/{svg_token}.svg").status_code == 404  # SVGs are never served publicly
    assert api.c.get("/api/public/assets/nonexistent.jpg").status_code == 404


def test_security_headers(demo):
    r = demo.get("/api/overview")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
