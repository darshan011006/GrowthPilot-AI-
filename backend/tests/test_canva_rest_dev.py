from __future__ import annotations

from types import SimpleNamespace

import pytest

from growthpilot.config import AppEnv
from growthpilot.services import canva_rest_dev as rest


def run_mocked(awaitable):
    coroutine = awaitable.__await__()
    try:
        while True:
            yielded = coroutine.send(None)
            if yielded is not None:
                raise AssertionError("mock coroutine unexpectedly suspended")
    except StopIteration as done:
        return done.value


class Response:
    def __init__(self, status, payload=None, content=b""):
        self.status_code, self.payload, self.content = status, payload or {}, content

    def json(self):
        return self.payload


class MockHttp:
    def __init__(self, *, unauthorized_once=False, **_kwargs):
        self.unauthorized_once = unauthorized_once
        self.did_401 = False
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.unauthorized_once and not self.did_401:
            self.did_401 = True
            return Response(401)
        return Response(200, {"job": {"id": "export-job", "status": "in_progress"}})

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if "/exports/" in url:
            return Response(200, {"job": {"status": "success", "artifacts": {
                "download": {"href": "https://cdn.example/poster.png?signature=hidden"}}}})
        return Response(200, content=b"\x89PNG\r\n\x1a\nmock")


def _settings(monkeypatch, app_env=AppEnv.DEVELOPMENT):
    monkeypatch.setattr(rest, "get_settings", lambda: SimpleNamespace(
        app_env=app_env, canva_client_id="client-configured", canva_client_secret="secret-configured",
        canva_mcp_url="https://api.canva.com/connect/v1/mcp"))


def test_rest_export_request_poll_and_nested_download_are_mocked(monkeypatch, tmp_path):
    _settings(monkeypatch)
    monkeypatch.delenv("CANVA_API_TOKEN", raising=False)
    monkeypatch.delenv("CANVA_REFRESH_TOKEN", raising=False)
    (tmp_path / ".env").write_text("CANVA_API_TOKEN=test-access\n", encoding="utf-8")
    ticks = [0.0]

    async def sleep(_seconds):
        ticks[0] += 1

    http_instances = []

    def factory(**kwargs):
        instance = MockHttp(**kwargs)
        http_instances.append(instance)
        return instance

    result = run_mocked(rest.export_png("design-123", client_factory=factory, sleep=sleep,
                                        clock=lambda: ticks[0], root=tmp_path))
    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    calls = http_instances[0].calls
    post = calls[0]
    assert post[1].endswith("/rest/v1/exports")
    assert post[2]["json"] == {"design_id": "design-123", "format": {
        "type": "png", "width": 1080, "height": 1350, "as_single_image": True}}
    assert any("/exports/export-job" in call[1] for call in calls)
    assert any("signature=hidden" in call[1] for call in calls)


def test_401_rotates_both_dotenv_tokens_atomically_before_retry(monkeypatch, tmp_path):
    _settings(monkeypatch)
    monkeypatch.delenv("CANVA_API_TOKEN", raising=False)
    monkeypatch.delenv("CANVA_REFRESH_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("KEEP_THIS=unchanged\nCANVA_API_TOKEN=old-access\nCANVA_REFRESH_TOKEN=old-refresh\n",
                        encoding="utf-8")
    rotated = []

    async def refresh(**kwargs):
        kwargs["persist_tokens"]("new-access", "new-refresh")
        rotated.append(True)
        return "new-access", "new-refresh"

    monkeypatch.setattr(rest, "refresh_mcp_tokens", refresh)
    ticks = [0.0]

    async def sleep(_seconds):
        ticks[0] += 1

    result = run_mocked(rest.export_png("design-456", client_factory=lambda **kwargs: MockHttp(
        unauthorized_once=True, **kwargs), sleep=sleep, clock=lambda: ticks[0], root=tmp_path))
    content = env_file.read_text(encoding="utf-8")
    pair_saved = "CANVA_API_TOKEN=new-access" in content and "CANVA_REFRESH_TOKEN=new-refresh" in content
    assert result.startswith(b"\x89PNG\r\n\x1a\n") and pair_saved and rotated and "KEEP_THIS=unchanged" in content


def test_rest_export_refuses_production_mode_without_request(monkeypatch, tmp_path):
    _settings(monkeypatch, AppEnv.PRODUCTION)

    def no_request(**_kwargs):
        raise AssertionError("production guard must run before HTTP")

    with pytest.raises(Exception, match="development-only"):
        run_mocked(rest.export_png("design-789", client_factory=no_request, root=tmp_path))
