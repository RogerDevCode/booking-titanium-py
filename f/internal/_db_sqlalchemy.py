# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "sqlalchemy>=2.0.25",
#   "asyncpg>=0.30.0"
# ]
# ///
from __future__ import annotations

import os
from collections.abc import AsyncGenerator  # noqa: TC003

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


def _get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return db_url


# Create async engine with production limits
async_engine: AsyncEngine = create_async_engine(
    _get_database_url(),
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True,
    future=True,
)

# Global async session factory
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base class for ORM entities."""

    pass


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """Dependency generator for database sessions."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
