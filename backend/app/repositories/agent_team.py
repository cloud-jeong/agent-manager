import uuid
from collections.abc import Iterable

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentTeam, Team


async def sync(db: AsyncSession, agent_id: uuid.UUID, team_ids: Iterable[uuid.UUID]) -> None:
    """Replace the agent's team assignments with `team_ids`."""
    await db.execute(delete(AgentTeam).where(AgentTeam.agent_id == agent_id))
    ids = set(team_ids)
    if ids:
        await db.execute(insert(AgentTeam), [{"agent_id": agent_id, "team_id": t} for t in ids])


async def get_teams_for_agents(
    db: AsyncSession, agent_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
    """Batch-load (team_id, team_name) per agent, ordered by team name."""
    ids = set(agent_ids)
    result: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {i: [] for i in ids}
    if not ids:
        return result
    rows = await db.execute(
        select(AgentTeam.agent_id, Team.id, Team.name)
        .join(Team, Team.id == AgentTeam.team_id)
        .where(AgentTeam.agent_id.in_(ids))
        .order_by(Team.name)
    )
    for r in rows:
        result[r.agent_id].append((r.id, r.name))
    return result
