"""Adapter registry. Demo mode exposes only simulated adapters; live mode only real ones."""

from __future__ import annotations

from ..config import get_settings
from ..platforms import ORDER
from .base import AdapterError, PlatformAdapter
from .demo_instagram import DemoAdapter, DemoInstagramAdapter
from .facebook import FacebookPageAdapter
from .instagram import InstagramAdapter
from .webhook import WebhookAdapter

_ALL: dict[str, PlatformAdapter] = {a.key: a for a in (
    DemoInstagramAdapter(), *[DemoAdapter(p) for p in ORDER if p != "instagram"],
    InstagramAdapter(), FacebookPageAdapter(), WebhookAdapter())}


def all_adapters() -> dict[str, PlatformAdapter]:
    return dict(_ALL)


def available_adapters() -> dict[str, PlatformAdapter]:
    demo = get_settings().is_demo
    return {k: a for k, a in _ALL.items() if a.external != demo}


def get_adapter(key: str) -> PlatformAdapter:
    a = available_adapters().get(key)
    if a is None:
        raise AdapterError(f"Adapter {key!r} is not available in {get_settings().app_mode.value} mode.")
    return a


def live_adapter_for(platform: str) -> PlatformAdapter | None:
    return next((a for a in _ALL.values() if a.external and a.platform == platform), None)


__all__ = ["AdapterError", "PlatformAdapter", "all_adapters", "available_adapters", "get_adapter",
           "live_adapter_for"]
