import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, TeamMember, User


async def list_all(db: AsyncSession) -> list[Team]:
    return list(await db.scalars(select(Team).order_by(Team.name)))


async def get(db: AsyncSession, team_id: uuid.UUID) -> Team | None:
    return await db.get(Team, team_id)


async def get_by_name(db: AsyncSession, name: str) -> Team | None:
    return await db.scalar(select(Team).where(Team.name == name))


async def existing_ids(db: AsyncSession, team_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = set(team_ids)
    if not ids:
        return set()
    return set(await db.scalars(select(Team.id).where(Team.id.in_(ids))))


async def get_members_for_teams(
    db: AsyncSession, team_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str, str, str]]]:
    """Batch-load (user_id, name, email, role) per team."""
    ids = set(team_ids)
    result: dict[uuid.UUID, list[tuple[uuid.UUID, str, str, str]]] = {i: [] for i in ids}
    if not ids:
        return result
    rows = await db.execute(
        select(TeamMember.team_id, User.id, User.name, User.email, TeamMember.role)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id.in_(ids))
        .order_by(User.name)
    )
    for r in rows:
        result[r.team_id].append((r.id, r.name, r.email, r.role))
    return result


async def create(db: AsyncSession, *, name: str, description: str | None) -> Team:
    team = Team(name=name, description=description)
    db.add(team)
    await db.flush()
    return team


async def delete_team(db: AsyncSession, team: Team) -> None:
    await db.delete(team)
    await db.flush()


async def upsert_member(
    db: AsyncSession, *, team_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    stmt = insert(TeamMember).values(team_id=team_id, user_id=user_id, role=role)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[TeamMember.team_id, TeamMember.user_id], set_={"role": role}
        )
    )


async def remove_member(db: AsyncSession, *, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        delete(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    return result.rowcount > 0
