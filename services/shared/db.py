"""
Async SQLAlchemy engine, session factory, and Base for all services.

Usage (FastAPI dependency):
    from shared.db import get_db
    async def route(db: AsyncSession = Depends(get_db)): ...

Usage (standalone):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MyModel))
"""

import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

_DATABASE_URL = os.environ.get(
    "POSTGRES_DSN",
    "postgresql+asyncpg://mas:changeme@localhost:5432/masdb",
)

engine = create_async_engine(
    _DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=os.environ.get("LOG_LEVEL", "INFO") == "DEBUG",
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base — import in every model module."""
    pass


async def get_db():
    """FastAPI dependency that yields a transactional AsyncSession."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
