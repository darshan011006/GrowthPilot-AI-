"""Importing this package registers every tool in ``agent.registry.REGISTRY``.

Tools are grouped by the specialist role that owns them: research, strategy, creative, verification,
distribution and learning (Performance Analyst)."""

from . import creative, distribution, learning, research, strategy, verification  # noqa: F401
