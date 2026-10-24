from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import ConfigError, Settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


def init_engine(settings: Settings) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(settings.database_url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised")
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialised")
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def create_schema(engine: Engine) -> None:
    """Create tables directly from the models (tests only; the app uses Alembic migrations)."""
    from . import models  # noqa: F401 - register tables

    Base.metadata.create_all(engine)


def alembic_config(engine: Engine):
    from pathlib import Path

    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.attributes["engine"] = engine
    return cfg


def migrate(engine: Engine) -> None:
    """Bring the schema to the latest Alembic revision."""
    from alembic import command

    command.upgrade(alembic_config(engine), "head")


def check_or_stamp_mode(settings: Settings) -> None:
    """Bind a database to one mode on first use and refuse to open it in the other mode."""
    from .models import AppMeta

    with session_scope() as db:
        row = db.execute(select(AppMeta).where(AppMeta.key == "mode")).scalar_one_or_none()
        if row is None:
            db.add(AppMeta(key="mode", value=settings.app_mode.value))
        elif row.value != settings.app_mode.value:
            raise ConfigError(
                f"This database belongs to {row.value!r} mode but the app is running in "
                f"{settings.app_mode.value!r} mode. Use a separate DATABASE_URL per mode."
            )
