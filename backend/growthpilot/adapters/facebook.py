"""Facebook Pages — live adapter (Graph API).

Implemented from Meta's Pages API documentation (checked 2026-10-24):
  * Login:      https://www.facebook.com/{version}/dialog/oauth (Facebook Login for Business), scopes
                pages_show_list, pages_read_engagement, pages_manage_posts
  * Token:      GET /{version}/oauth/access_token?code=… → user token; ?grant_type=fb_exchange_token → long-lived
  * Pages:      GET /me/accounts?fields=id,name,access_token,tasks → Page access tokens
  * Photo post: POST /{page-id}/photos (url, message) → {"id": photo id, "post_id"}
  * Multi-photo: POST /{page-id}/photos (url, published=false) per image, then POST /{page-id}/feed with
                attached_media[i]={"media_fbid": id} and message
  * Text post:  POST /{page-id}/feed (message)
  * Verify:     GET /{post-id}?fields=id,permalink_url,created_time
  * Counts:     GET /{post-id}?fields=reactions.summary(total_count),comments.summary(total_count),shares

Status: implemented and tested against a mocked Graph API; not yet verified with a real Page.
Page insights (reach) are not fetched; only publicly visible counts are collected.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlencode

from ..config import get_settings
from ..models import Platform
from ..research.net import client
from .base import (
    AccountInfo,
    AdapterError,
    Capabilities,
    ConnectionContext,
    Metrics,
    PublishPayload,
    PublishResult,
    StatusResult,
)

SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts"]
GRAPH = "https://graph.facebook.com"


def _raise(resp, what: str) -> None:
    if resp.is_success:
        return
    msg, code = "", None
    try:
        err = resp.json().get("error", {})
        msg = str(err.get("message", ""))[:300]
        code = err.get("code")
    except Exception:  # noqa: BLE001
        msg = resp.text[:200]
    reauth = resp.status_code == 401 or code in (190,)
    retryable = resp.status_code == 429 or resp.status_code >= 500 or code in (1, 2, 4, 17, 32, 341, 613)
    raise AdapterError(f"Facebook {what} failed (HTTP {resp.status_code}): {msg}." + (" Reconnect Facebook." if reauth
                                                                                       else ""),
                       retryable=retryable, reauth=reauth)


class FacebookPageAdapter:
    key = "facebook"
    platform = Platform.FACEBOOK.value
    label = "Facebook Page"
    external = True
    maturity = "implemented-unverified"
    capabilities = Capabilities(oauth=True, identity=True, publish=True, scheduling="app-managed",
                                status_verification=True, analytics=True, content_types=("post", "carousel", "text"))

    @property
    def version(self) -> str:
        return get_settings().facebook_api_version

    # ── OAuth ────────────────────────────────────────────────────────────
    def authorize_url(self, state: str) -> str:
        s = get_settings()
        return f"https://www.facebook.com/{self.version}/dialog/oauth?" + urlencode(
            {"client_id": s.meta_app_id, "redirect_uri": s.facebook_redirect, "state": state,
             "scope": ",".join(SCOPES), "response_type": "code"})

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Code → long-lived user token → the Pages this person can post to (each with its Page token)."""
        s = get_settings()
        with client() as c:
            resp = c.get(f"{GRAPH}/{self.version}/oauth/access_token", params={
                "client_id": s.meta_app_id, "client_secret": s.meta_app_secret, "redirect_uri": s.facebook_redirect,
                "code": code})
            _raise(resp, "token exchange")
            short = resp.json()["access_token"]
            resp = c.get(f"{GRAPH}/{self.version}/oauth/access_token", params={
                "grant_type": "fb_exchange_token", "client_id": s.meta_app_id, "client_secret": s.meta_app_secret,
                "fb_exchange_token": short})
            _raise(resp, "long-lived token exchange")
            long = resp.json()
            resp = c.get(f"{GRAPH}/{self.version}/me/accounts", params={"fields": "id,name,access_token,tasks"},
                         headers={"Authorization": f"Bearer {long['access_token']}"})
            _raise(resp, "Page lookup")
            pages = resp.json().get("data", [])
        usable = [p for p in pages if "CREATE_CONTENT" in (p.get("tasks") or []) and p.get("access_token")]
        if not usable:
            raise AdapterError("No Facebook Page where you can create content was shared with the app.")
        return {"user_token": long["access_token"], "issued_at": int(time.time()),
                "expires_at": int(time.time()) + int(long.get("expires_in", 0) or 0) if long.get("expires_in") else None,
                "pages": [{"id": p["id"], "name": p.get("name", ""), "access_token": p["access_token"]} for p in usable]}

    def _page(self, ctx: ConnectionContext) -> tuple[str, str]:
        pages = ctx.credentials.get("pages") or []
        page = next((p for p in pages if p["id"] == ctx.account_id), pages[0] if pages else None)
        if not page:
            raise AdapterError("Facebook isn't authorised for any Page. Connect a Page.", reauth=True)
        return page["id"], page["access_token"]

    def _call(self, method: str, path: str, token: str, what: str, **data) -> dict:
        with client() as c:
            if method == "GET":
                resp = c.get(f"{GRAPH}/{self.version}/{path}", params=data, headers={"Authorization": f"Bearer {token}"})
            else:
                resp = c.post(f"{GRAPH}/{self.version}/{path}", data=data, headers={"Authorization": f"Bearer {token}"})
        _raise(resp, what)
        return resp.json()

    # ── adapter interface ────────────────────────────────────────────────
    def verify_connection(self, ctx: ConnectionContext) -> AccountInfo:
        page_id, token = self._page(ctx)
        me = self._call("GET", page_id, token, "Page lookup", fields="id,name,link")
        return AccountInfo(account_id=str(me.get("id") or page_id), label=me.get("name") or "Facebook Page",
                           detail={"link": me.get("link")})

    def publish(self, ctx: ConnectionContext, payload: PublishPayload) -> PublishResult:
        page_id, token = self._page(ctx)
        for u in payload.image_urls:
            if not u.startswith("https://"):
                raise AdapterError("Facebook must fetch images from a public HTTPS URL. Set BASE_URL to a public "
                                   "HTTPS address.")
        if not payload.image_urls:
            out = self._call("POST", f"{page_id}/feed", token, "text post", message=payload.caption)
            post_id = out["id"]
        elif len(payload.image_urls) == 1:
            out = self._call("POST", f"{page_id}/photos", token, "photo post", url=payload.image_urls[0],
                             message=payload.caption)
            post_id = out.get("post_id") or out["id"]
        else:
            media = []
            for u in payload.image_urls[:10]:
                ph = self._call("POST", f"{page_id}/photos", token, "photo upload", url=u, published="false")
                media.append(ph["id"])
            fields = {f"attached_media[{i}]": json.dumps({"media_fbid": m}) for i, m in enumerate(media)}
            out = self._call("POST", f"{page_id}/feed", token, "multi-photo post", message=payload.caption, **fields)
            post_id = out["id"]
        return PublishResult(external_id=str(post_id), url=None, provider_status="PUBLISHED",
                             summary=f"Facebook accepted the post (id {post_id}).")

    def publication_status(self, ctx: ConnectionContext, external_id: str) -> StatusResult:
        _page_id, token = self._page(ctx)
        try:
            post = self._call("GET", external_id, token, "post lookup", fields="id,permalink_url,created_time")
        except AdapterError as exc:
            if "HTTP 400" in str(exc) or "HTTP 404" in str(exc):
                return StatusResult(state="not_found", detail=str(exc))
            raise
        if post.get("id"):
            return StatusResult(state="published", url=post.get("permalink_url"),
                                detail=f"Facebook reports post {post['id']} at {post.get('created_time', '?')}.")
        return StatusResult(state="unknown", detail="Facebook returned no post id.")

    def fetch_metrics(self, ctx: ConnectionContext, external_id: str, *, hours_since: float, hints: dict) -> Metrics | None:
        _page_id, token = self._page(ctx)
        d = self._call("GET", external_id, token, "post counts",
                       fields="reactions.summary(total_count),comments.summary(total_count),shares")
        likes = ((d.get("reactions") or {}).get("summary") or {}).get("total_count")
        comments = ((d.get("comments") or {}).get("summary") or {}).get("total_count")
        shares = (d.get("shares") or {}).get("count")
        return Metrics(reach=None, likes=likes, comments=comments, shares=shares,
                       raw={"counts": {"reactions": likes, "comments": comments, "shares": shares},
                            "note": "Public counts only; Page insights (reach) are not collected."})
