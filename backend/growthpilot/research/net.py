"""Outbound HTTP with SSRF protection. Every fetch of a user- or model-supplied URL goes through here."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = "GrowthPilotBot/0.1 (+marketing research; respects robots.txt)"

_transport: httpx.BaseTransport | None = None
_resolver = socket.getaddrinfo


class BlockedURL(ValueError):
    """URL not allowed (scheme, credentials, private address, or domain policy)."""


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests inject an httpx.MockTransport."""
    global _transport
    _transport = transport


def set_resolver(fn) -> None:
    global _resolver
    _resolver = fn


def client(**kwargs: Any) -> httpx.Client:
    kwargs.setdefault("timeout", httpx.Timeout(15.0, connect=5.0))
    kwargs.setdefault("follow_redirects", False)
    headers = {"User-Agent": USER_AGENT}
    headers.update(kwargs.pop("headers", {}) or {})
    kwargs["headers"] = headers
    if _transport is not None:
        kwargs["transport"] = _transport
    return httpx.Client(**kwargs)


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast
        or addr.is_unspecified or (addr.version == 6 and addr.ipv4_mapped and not _is_public_ip(str(addr.ipv4_mapped)))
    )


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def domain_allowed(host: str, allowed: list[str]) -> bool:
    host = host.lower()
    for d in allowed:
        d = d.lower().strip().lstrip("*.").rstrip("/")
        if d.startswith(("http://", "https://")):
            d = host_of(d)
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


def check_url(url: str, *, allow_http: bool = False, allowed_domains: list[str] | None = None) -> None:
    p = urlparse(url)
    if p.scheme not in ("https", "http") or not p.hostname:
        raise BlockedURL("Only absolute http(s) URLs can be fetched.")
    if p.scheme == "http" and not allow_http:
        raise BlockedURL("Only https URLs can be fetched.")
    if p.username or p.password:
        raise BlockedURL("URLs with embedded credentials are not allowed.")
    if p.port not in (None, 80, 443):
        raise BlockedURL("Non-standard ports are not allowed.")
    if allowed_domains is not None and not domain_allowed(p.hostname, allowed_domains):
        raise BlockedURL(f"{p.hostname} is not in this brand's permitted research sources.")
    try:
        infos = _resolver(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURL(f"Could not resolve {p.hostname}.") from exc
    for info in infos:
        if not _is_public_ip(info[4][0]):
            raise BlockedURL("URL resolves to a private or internal address.")


def safe_get(url: str, *, max_bytes: int = 1_000_000, allowed_domains: list[str] | None = None,
             max_redirects: int = 3, headers: dict | None = None) -> httpx.Response:
    """GET with manual redirect handling so every hop is re-validated."""
    current = url
    with client(headers=headers or {}) as c:
        for _ in range(max_redirects + 1):
            check_url(current, allowed_domains=allowed_domains)
            with c.stream("GET", current) as resp:
                if resp.is_redirect:
                    loc = resp.headers.get("location", "")
                    current = str(httpx.URL(current).join(loc))
                    continue
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks)
                return httpx.Response(resp.status_code, headers=resp.headers, content=body,
                                      request=httpx.Request("GET", current))
    raise BlockedURL("Too many redirects.")
