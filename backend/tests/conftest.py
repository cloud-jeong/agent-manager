"""Tests run against a real Postgres database (AGENT_MANAGER_TEST_DATABASE_URL).

The schema is created once per session and every table is truncated after each test.
"""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["AGENT_MANAGER_TESTING"] = "true"
os.environ["AGENT_MANAGER_DATABASE_URL"] = os.environ.get(
    "AGENT_MANAGER_TEST_DATABASE_URL",
    "postgresql+asyncpg://agent_manager:agent_manager@localhost:5433/agent_manager_test",
)

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Team, User  # noqa: E402
from app.repositories import team as team_repo  # noqa: E402
from app.repositories import user as user_repo  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

# bcrypt is slow on purpose; hash the shared test password once.
TEST_PASSWORD = "password123"
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def make_user() -> Callable[..., Awaitable[User]]:
    async def _make(role: str = "member", name: str | None = None) -> User:
        suffix = uuid.uuid4().hex[:8]
        async with SessionLocal() as db:
            user = await user_repo.create(
                db,
                email=f"user-{suffix}@test.local",
                name=name or f"User {suffix}",
                password_hash=_TEST_PASSWORD_HASH,
                role=role,
            )
            await db.commit()
            return user

    return _make


@pytest.fixture
def make_team() -> Callable[..., Awaitable[Team]]:
    async def _make(name: str | None = None, members: dict[uuid.UUID, str] | None = None) -> Team:
        async with SessionLocal() as db:
            team = await team_repo.create(
                db, name=name or f"Team {uuid.uuid4().hex[:8]}", description=None
            )
            for user_id, role in (members or {}).items():
                await team_repo.upsert_member(db, team_id=team.id, user_id=user_id, role=role)
            await db.commit()
            return team

    return _make


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
