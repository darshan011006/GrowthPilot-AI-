"""Development-only Canva REST PNG export fallback.

This path intentionally reads the local developer's REST bearer-token pair. It must not be
enabled in production; normal connected-account use remains the authenticated MCP client.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ..config import PROJECT_ROOT, AppEnv, get_settings
from ..creative.canva_mcp import CanvaMCPError, _nested, refresh_mcp_tokens

REST_ROOT = "https://api.canva.com/rest/v1"


def _dotenv_value(name: str, path: Path | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    env_path = path or PROJECT_ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.startswith("export "):
            candidate = candidate[7:].lstrip()
        key, sep, value = candidate.partition("=")
        if sep and key.strip() == name:
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return None


def _persist_rotated_tokens(access: str, refresh: str, path: Path | None = None) -> None:
    """Atomically rotate both development REST tokens in the root dotenv file."""
    if any("\n" in value or "\r" in value for value in (access, refresh)):
        raise CanvaMCPError("Canva REST returned an invalid token value.")
    env_path = path or PROJECT_ROOT / ".env"
    try:
        original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        lines = original.splitlines(keepends=True)
        replacements = {"CANVA_API_TOKEN": access, "CANVA_REFRESH_TOKEN": refresh}
        seen: set[str] = set()
        output: list[str] = []
        for line in lines:
            stripped = line.lstrip()
            key, sep, _value = stripped.partition("=")
            if sep and key.strip() in replacements:
                name = key.strip()
                if name not in seen:
                    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                    output.append(f"{name}={replacements[name]}{newline}")
                    seen.add(name)
                continue
            output.append(line)
        for name, value in replacements.items():
            if name not in seen:
                if output and not output[-1].endswith(("\n", "\r")):
                    output[-1] += "\n"
                output.append(f"{name}={value}\n")
        fd, temporary = tempfile.mkstemp(prefix=".canva-rest-", suffix=".tmp", dir=env_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.writelines(output)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, env_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError:
        raise CanvaMCPError("Rotated Canva REST credentials could not be saved atomically.") from None
    os.environ["CANVA_API_TOKEN"] = access
    os.environ["CANVA_REFRESH_TOKEN"] = refresh


def _https_urls(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from _https_urls(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _https_urls(child)
    elif isinstance(value, str) and value.startswith("https://"):
        yield value


async def export_png(design_id: str, *, client_factory=httpx.AsyncClient,
                     sleep=asyncio.sleep, clock=time.monotonic,
                     root: Path | None = None) -> bytes:
    """Create/poll a Canva REST export and return validated PNG bytes; never return its signed URL."""
    settings = get_settings()
    if settings.app_env == AppEnv.PRODUCTION:
        raise CanvaMCPError("Canva REST bearer-token export fallback is development-only.")
    token = _dotenv_value("CANVA_API_TOKEN", root / ".env" if root else None)
    refresh = _dotenv_value("CANVA_REFRESH_TOKEN", root / ".env" if root else None)
    if not token:
        raise CanvaMCPError("Development Canva REST export needs CANVA_API_TOKEN.")

    async with client_factory(timeout=30, follow_redirects=False) as client:
        async def request(method: str, url: str, **kwargs):
            nonlocal token, refresh
            response = await getattr(client, method)(url, **kwargs)
            if response.status_code != 401:
                return response
            if not refresh or not settings.canva_client_id or not settings.canva_client_secret:
                raise CanvaMCPError("Canva REST returned HTTP 401 and development token refresh is not configured.")
            try:
                token, refresh = await refresh_mcp_tokens(client_id=settings.canva_client_id,
                    client_secret=settings.canva_client_secret, refresh_token=refresh,
                    persist_tokens=lambda access, rotated: _persist_rotated_tokens(
                        access, rotated, root / ".env" if root else None), mcp_url=settings.canva_mcp_url)
            except CanvaMCPError as exc:
                raise CanvaMCPError(f"Canva REST token refresh failed ({exc.http_status or 'status unavailable'}).",
                                    http_status=exc.http_status, exception_type=exc.exception_type) from None
            headers = dict(kwargs.get("headers") or {})
            headers["Authorization"] = f"Bearer {token}"
            return await getattr(client, method)(url, **(kwargs | {"headers": headers}))

        headers = {"Authorization": f"Bearer {token}"}
        response = await request("post", REST_ROOT + "/exports", headers=headers, json={
            "design_id": design_id,
            "format": {"type": "png", "width": 1080, "height": 1350, "as_single_image": True},
        })
        if response.status_code >= 400:
            raise CanvaMCPError(f"Canva REST export failed with HTTP {response.status_code}.")
        payload = response.json()
        export_id = _nested(payload, "export_id", "exportId", "id")
        if not isinstance(export_id, str):
            raise CanvaMCPError("Canva REST export response omitted the export job id.")
        deadline = clock() + 120
        while clock() < deadline:
            state = str(_nested(payload, "status") or "").casefold()
            if state in {"success", "succeeded", "completed", "done"}:
                break
            if state in {"failed", "error", "cancelled", "canceled"}:
                raise CanvaMCPError("Canva REST export job failed.")
            await sleep(3)
            response = await request("get", f"{REST_ROOT}/exports/{quote(export_id, safe='')}",
                                     headers={"Authorization": f"Bearer {token}"})
            if response.status_code >= 400:
                raise CanvaMCPError(f"Canva REST export polling failed with HTTP {response.status_code}.")
            payload = response.json()
        else:
            raise CanvaMCPError("Canva REST export timed out after 120 seconds.")
        for url in _https_urls(payload):
            try:
                download = await client.get(url, follow_redirects=True)
            except httpx.HTTPError:
                continue
            if download.status_code == 200 and download.content.startswith(b"\x89PNG\r\n\x1a\n"):
                return download.content
        raise CanvaMCPError("Canva REST export did not return a downloadable PNG.")
