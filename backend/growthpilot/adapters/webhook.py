"""Generic signed webhook adapter (live). Sends approved content to a URL you control (Zapier, Make, n8n,
your own service). Headers: X-GrowthPilot-Timestamp and
X-GrowthPilot-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<body>" using the signing secret>."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from ..config import get_settings
from ..research.net import BlockedURL, check_url, client, host_of
from .base import (
    AccountInfo,
    AdapterError,
    Capabilities,
    ConnectionContext,
    PublishPayload,
    PublishResult,
    StatusResult,
)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def validate_url(url: str) -> None:
    allow = get_settings().allow_insecure_webhooks
    try:
        if allow:
            if not url.startswith(("http://", "https://")):
                raise BlockedURL("Webhook URL must be http(s).")
        else:
            check_url(url)
    except BlockedURL as exc:
        raise AdapterError(f"Webhook URL not allowed: {exc}") from exc


class WebhookAdapter:
    key = "webhook"
    platform = "any"
    label = "Signed webhook (Zapier / Make / n8n / custom)"
    external = True
    maturity = "tested-mock-receiver"  # exercised in the test suite against a mock receiver only
    capabilities = Capabilities(oauth=False, identity=False, publish=True, scheduling="app-managed",
                                status_verification=False, analytics=False, content_types=("post", "carousel", "reel"))

    def _post(self, ctx: ConnectionContext, event: dict) -> dict:
        url = ctx.config.get("url", "")
        validate_url(url)
        secret = ctx.credentials.get("signing_secret")
        if not secret:
            raise AdapterError("Webhook signing secret missing; recreate the connection.")
        body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()
        ts = str(int(time.time()))
        try:
            with client() as c:
                resp = c.post(url, content=body, headers={
                    "Content-Type": "application/json", "X-GrowthPilot-Timestamp": ts,
                    "X-GrowthPilot-Signature": sign(secret, ts, body), "X-GrowthPilot-Event": event["event"]})
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"Webhook request failed: {type(exc).__name__}", retryable=True) from exc
        if resp.is_redirect:
            raise AdapterError("Webhook responded with a redirect; redirects are not followed.")
        if not resp.is_success:
            raise AdapterError(f"Webhook returned HTTP {resp.status_code}.",
                               retryable=resp.status_code >= 500 or resp.status_code == 429)
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def verify_connection(self, ctx: ConnectionContext) -> AccountInfo:
        self._post(ctx, {"event": "ping", "sent_at": int(time.time())})
        return AccountInfo(account_id=host_of(ctx.config.get("url", "")), label=host_of(ctx.config.get("url", "")))

    def publish(self, ctx: ConnectionContext, payload: PublishPayload) -> PublishResult:
        data = self._post(ctx, {"event": "content.publish", "sent_at": int(time.time()), "content": {
            "id": payload.content_id, "version": payload.version, "platform": payload.platform,
            "content_type": payload.content_type, "caption": payload.caption, "image_urls": payload.image_urls,
            "alt_text": payload.alt_text}})
        ext = str(data.get("id") or f"webhook-{payload.content_id}-v{payload.version}")
        url = data.get("url") if isinstance(data.get("url"), str) and data["url"].startswith("https://") else None
        return PublishResult(external_id=ext, url=url, provider_status="DELIVERED",
                             summary="Delivered to webhook (HTTP 2xx). Whether it was posted depends on the receiver.")

    def publication_status(self, ctx: ConnectionContext, external_id: str) -> StatusResult:
        return StatusResult(state="unknown", detail="Webhook receivers don't report publication status.")

    def fetch_metrics(self, ctx, external_id, *, hours_since, hints):
        return None
