import uuid
from collections.abc import Iterable

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentUser, User


async def sync(db: AsyncSession, agent_id: uuid.UUID, shares: dict[uuid.UUID, str]) -> None:
    """Replace the agent's user shares with `shares` (user_id -> level)."""
    await db.execute(delete(AgentUser).where(AgentUser.agent_id == agent_id))
    if shares:
        await db.execute(
            insert(AgentUser),
            [{"agent_id": agent_id, "user_id": u, "level": lvl} for u, lvl in shares.items()],
        )


async def get_users_for_agents(
    db: AsyncSession, agent_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str, str, str]]]:
    """Batch-load (user_id, name, email, level) per agent."""
    ids = set(agent_ids)
    result: dict[uuid.UUID, list[tuple[uuid.UUID, str, str, str]]] = {i: [] for i in ids}
    if not ids:
        return result
    rows = await db.execute(
        select(AgentUser.agent_id, User.id, User.name, User.email, AgentUser.level)
        .join(User, User.id == AgentUser.user_id)
        .where(AgentUser.agent_id.in_(ids))
        .order_by(User.name)
    )
    for r in rows:
        result[r.agent_id].append((r.id, r.name, r.email, r.level))
    return result
