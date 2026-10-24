from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from growthpilot import config
from growthpilot.adapters.base import AdapterError, ConnectionContext, PublishPayload
from growthpilot.adapters.webhook import WebhookAdapter
from growthpilot.models import MetricSnapshot
from growthpilot.research import net
from growthpilot.services.analytics import er, interactions

from .conftest import _configure, make_client


def test_live_mode_requires_real_secrets(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, "live")
    monkeypatch.setenv("SECRET_KEY", "short")
    config.get_settings.cache_clear()
    with pytest.raises(config.ConfigError, match="SECRET_KEY"):
        config.get_settings()
    _configure(monkeypatch, tmp_path, "live")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'demo.db'}")
    config.get_settings.cache_clear()
    with pytest.raises(config.ConfigError, match="demo database"):
        config.get_settings()


def test_demo_forces_publishing_off(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, "demo", LIVE_PUBLISHING_ENABLED="true")
    assert config.get_settings().live_publishing_enabled is False


def test_database_bound_to_mode(monkeypatch, tmp_path):
    make_client(monkeypatch, tmp_path, "demo")
    db_url = f"sqlite:///{tmp_path / 'demo.db'}"
    _configure(monkeypatch, tmp_path, "live", DATABASE_URL=db_url.replace("demo.db", "shared.db"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared.db'}")
    from growthpilot.api.app import create_app

    create_app(start_worker=False)  # stamps shared.db as live
    _configure(monkeypatch, tmp_path, "demo")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared.db'}")
    config.get_settings.cache_clear()
    with pytest.raises(config.ConfigError, match="belongs to 'live'"):
        create_app(start_worker=False)


def test_problems_never_include_values(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, "live", META_APP_ID="123")
    probs = config.get_settings().problems()
    keys = {p["key"] for p in probs}
    assert "LLM_API_KEY" in keys and "SEARCH_API_KEY" in keys
    assert "123" not in json.dumps(probs)


def test_metric_formulas_keep_missing_data_missing():
    s = MetricSnapshot(reach=1000, likes=40, comments=5, shares=3, saves=2, source="manual")
    assert interactions(s) == 50 and er(s) == 0.05
    partial = MetricSnapshot(reach=1000, likes=40, comments=None, shares=3, saves=2, source="manual")
    assert interactions(partial) is None and er(partial) is None


def test_webhook_signature_and_guards(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, "live")
    net.set_resolver(lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", 443))])
    seen = {}

    def handler(req):
        seen["sig"] = req.headers["x-growthpilot-signature"]
        seen["ts"] = req.headers["x-growthpilot-timestamp"]
        seen["body"] = req.content
        return httpx.Response(200, json={"id": "ext-1", "url": "https://social.example.com/p/1"})

    net.set_transport(httpx.MockTransport(handler))
    ctx = ConnectionContext(connection_id=1, account_id="", config={"url": "https://hooks.example.com/x"},
                            credentials={"signing_secret": "topsecret"})
    res = WebhookAdapter().publish(ctx, PublishPayload(content_id=1, version=1, platform="instagram",
                                                       content_type="post", caption="hi"))
    expected = "sha256=" + hmac.new(b"topsecret", seen["ts"].encode() + b"." + seen["body"], hashlib.sha256).hexdigest()
    assert seen["sig"] == expected and res.external_id == "ext-1"
    net.set_transport(httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://10.0.0.1/"})))
    with pytest.raises(AdapterError, match="redirect"):
        WebhookAdapter().publish(ctx, PublishPayload(content_id=1, version=1, platform="x", content_type="post",
                                                     caption="hi"))
    net.set_resolver(lambda host, port, proto=0: [(2, 1, 6, "", ("192.168.1.5", 443))])
    with pytest.raises(AdapterError, match="private"):
        WebhookAdapter().verify_connection(ctx)


def test_migrations_from_clean_state(monkeypatch, tmp_path):
    from alembic import command

    from growthpilot.db import alembic_config, init_engine, migrate

    _configure(monkeypatch, tmp_path, "demo")
    engine = init_engine(config.get_settings())
    migrate(engine)
    command.check(alembic_config(engine))  # raises if models and migrations drift


def test_demo_adapter_never_reaches_network(demo_seeded):
    def boom(req):
        raise AssertionError(f"unexpected network call to {req.url}")

    net.set_transport(httpx.MockTransport(boom))
    r = demo_seeded.post("/api/agent/runs", json={"goal": "Evaluate last month's results"}).json()
    from .conftest import run_worker

    run_worker()
    assert demo_seeded.get(f"/api/agent/runs/{r['id']}").json()["status"] == "completed"
