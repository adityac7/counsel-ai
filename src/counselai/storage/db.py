"""Database engine, session factory, and base model for SQLite.

Provides both async (for FastAPI routes) and sync (for dashboard
service layers) session factories from a single configuration.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

# Default SQLite path — override via init_db()
_DEFAULT_URL = "sqlite+aiosqlite:///counselai.db"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# Sync engine/factory for dashboard service layers
_sync_engine: Engine | None = None
_sync_session_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


def _build_engine(url: str) -> AsyncEngine:
    """Create an async engine tuned for SQLite."""
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # WAL mode + foreign keys for SQLite
        connect_args = {"check_same_thread": False}

    return create_async_engine(
        url,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


def _async_to_sync_url(url: str) -> str:
    """Convert an async SQLAlchemy URL to its sync equivalent."""
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    return url


def init_db(url: str = _DEFAULT_URL) -> None:
    """Initialise the global engine and session factory.

    Safe to call multiple times — subsequent calls are no-ops unless
    the URL changes.
    """
    global _engine, _session_factory, _sync_engine, _sync_session_factory

    if _engine is not None:
        return

    _engine = _build_engine(url)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Enable FK enforcement on every SQLite connection (PRAGMA is per-connection)
    if url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _set_sqlite_fk(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # Build sync engine for dashboard service layers
    sync_url = _async_to_sync_url(url)
    connect_args: dict = {}
    if sync_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    _sync_engine = create_engine(sync_url, echo=False, connect_args=connect_args)

    if sync_url.startswith("sqlite"):
        @event.listens_for(_sync_engine, "connect")
        def _set_sqlite_fk_sync(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    _sync_session_factory = sessionmaker(bind=_sync_engine, expire_on_commit=False)

    logger.info("Database engine initialised: %s", url.split("?")[0])


def get_engine() -> AsyncEngine:
    """Return the global engine, initialising with defaults if needed."""
    if _engine is None:
        init_db()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the global session factory."""
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session — use as a FastAPI dependency.

    Example::

        @router.get("/")
        async def index(db: AsyncSession = Depends(get_db)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_sync_session_factory() -> sessionmaker[Session]:
    """Return the global sync session factory."""
    if _sync_session_factory is None:
        init_db()
    assert _sync_session_factory is not None
    return _sync_session_factory


def get_sync_db() -> Generator[Session, None, None]:
    """Yield a sync session — use as a FastAPI dependency for sync routes.

    Example::

        @router.get("/")
        def index(db: Session = Depends(get_sync_db)):
            ...
    """
    factory = get_sync_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context-manager wrapper around get_db for non-FastAPI usage."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all tables from metadata (dev/test convenience)."""
    engine = get_engine()
    async with engine.begin() as conn:
        # Enable WAL mode for SQLite
        if str(engine.url).startswith("sqlite"):
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("All tables created.")


async def health_check() -> dict[str, str]:
    """Run a lightweight connectivity check."""
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()
        return {"status": "ok", "database": str(engine.url).split("?")[0]}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def close_db() -> None:
    """Dispose of all engine connection pools."""
    global _engine, _session_factory, _sync_engine, _sync_session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None
        _sync_session_factory = None
    logger.info("Database engines disposed.")
