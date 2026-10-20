from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    **({"poolclass": NullPool} if _settings.testing else {"pool_pre_ping": True}),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
