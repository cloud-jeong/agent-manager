import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MemberSettings, Team, TeamMember, User


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.lower()))


async def list_all(db: AsyncSession) -> list[User]:
    return list(await db.scalars(select(User).order_by(User.name)))


async def get_many(db: AsyncSession, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, User]:
    ids = set(user_ids)
    if not ids:
        return {}
    rows = await db.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in rows}


async def create(db: AsyncSession, *, email: str, name: str, password_hash: str, role: str) -> User:
    user = User(email=email.lower(), name=name, password_hash=password_hash, role=role)
    db.add(user)
    await db.flush()
    return user


async def get_team_memberships(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str]]:
    """Return (team_id, team_name, role) for every team the user belongs to."""
    rows = await db.execute(
        select(Team.id, Team.name, TeamMember.role)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .order_by(Team.name)
    )
    return [(r.id, r.name, r.role) for r in rows]


async def get_default_agent_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(
        select(MemberSettings.default_agent_id).where(MemberSettings.user_id == user_id)
    )


async def set_default_agent_id(
    db: AsyncSession, user_id: uuid.UUID, agent_id: uuid.UUID | None
) -> None:
    settings = await db.get(MemberSettings, user_id)
    if settings is None:
        db.add(MemberSettings(user_id=user_id, default_agent_id=agent_id))
    else:
        settings.default_agent_id = agent_id
    await db.flush()
