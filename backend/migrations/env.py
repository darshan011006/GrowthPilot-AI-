"""Alembic environment. The engine is supplied by GrowthPilot (``db.alembic_config``) or built from settings."""

from __future__ import annotations

from alembic import context

from growthpilot import models  # noqa: F401 - register tables
from growthpilot.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _engine():
    engine = config.attributes.get("engine")
    if engine is not None:
        return engine
    from growthpilot.config import get_settings

    return make_engine(get_settings().database_url)


def run_migrations_offline() -> None:
    from growthpilot.config import get_settings

    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = _engine()
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
