"""Async database engine, session factory, and base model for SQLite."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

# Default SQLite path — override via init_db()
_DEFAULT_URL = "sqlite+aiosqlite:///counselai.db"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


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


def init_db(url: str = _DEFAULT_URL) -> None:
    """Initialise the global engine and session factory.

    Safe to call multiple times — subsequent calls are no-ops unless
    the URL changes.
    """
    global _engine, _session_factory

    if _engine is not None:
        return

    _engine = _build_engine(url)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
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
    """Dispose of the engine connection pool."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed.")
