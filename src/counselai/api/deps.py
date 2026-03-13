"""Shared FastAPI dependencies (DB sessions, auth hooks, etc.)."""

from typing import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from counselai.storage.db import get_db as _get_async_db
from counselai.storage.db import get_sync_db as _get_sync_db


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for FastAPI route injection."""
    async for session in _get_async_db():
        yield session


def get_sync_db() -> Generator[Session, None, None]:
    """Yield a sync DB session for sync FastAPI routes (dashboard etc.)."""
    yield from _get_sync_db()
