"""Adapter registry. Demo mode exposes only mock adapters; live mode only real ones."""

from __future__ import annotations

from ..config import get_settings
from .base import AdapterError, PlatformAdapter
from .demo_instagram import DemoInstagramAdapter
from .instagram import InstagramAdapter
from .webhook import WebhookAdapter

_ALL: dict[str, PlatformAdapter] = {a.key: a for a in (DemoInstagramAdapter(), InstagramAdapter(), WebhookAdapter())}


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


__all__ = ["AdapterError", "PlatformAdapter", "all_adapters", "available_adapters", "get_adapter"]
