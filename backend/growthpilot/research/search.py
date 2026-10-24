"""Web search providers. Brave Search API is implemented (https://api.search.brave.com/res/v1/web/search)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from .net import client


class SearchUnavailable(RuntimeError):
    """No search provider configured (or not allowed in this mode)."""


class SearchError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    age: str | None
    provider: str


def search(query: str, *, count: int = 8, country: str | None = None, freshness: str | None = None) -> list[SearchResult]:
    s = get_settings()
    if s.is_demo:
        raise SearchUnavailable("Live web search is disabled in demo mode (no external calls).")
    if not s.search_configured:
        raise SearchUnavailable("No search provider configured. Set SEARCH_PROVIDER=brave and SEARCH_API_KEY.")
    params: dict = {"q": query[:400], "count": max(1, min(count, 20))}
    if country:
        params["country"] = country
    if freshness in {"pd", "pw", "pm", "py"}:
        params["freshness"] = freshness
    try:
        with client(headers={"Accept": "application/json", "X-Subscription-Token": s.search_api_key}) as c:
            resp = c.get("https://api.search.brave.com/res/v1/web/search", params=params)
    except Exception as exc:  # noqa: BLE001
        raise SearchError(f"Search request failed: {type(exc).__name__}", retryable=True) from exc
    if resp.status_code == 401 or resp.status_code == 403:
        raise SearchError(f"Search provider rejected the API key (HTTP {resp.status_code}).")
    if resp.status_code == 429:
        raise SearchError("Search provider rate limit reached.", retryable=True)
    if resp.status_code >= 400:
        raise SearchError(f"Search provider returned HTTP {resp.status_code}.", retryable=resp.status_code >= 500)
    data = resp.json()
    out = []
    for r in (data.get("web") or {}).get("results", [])[:count]:
        url = r.get("url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        out.append(SearchResult(title=(r.get("title") or "")[:300], url=url[:1000],
                                snippet=(r.get("description") or "")[:600], age=r.get("age") or r.get("page_age"),
                                provider="brave"))
    return out
