"""Shared FastAPI dependencies (DB sessions, auth hooks, etc.)."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from counselai.storage.db import get_db as _get_db


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for FastAPI route injection."""
    async for session in _get_db():
        yield session
