import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentLabel, AgentTeam, LabelKey, LabelValue, MemberSettings, Team


@dataclass
class AgentListFilters:
    name: str | None = None
    agent_type: str | None = None
    scope: str | None = None
    team_ids: list[uuid.UUID] = field(default_factory=list)
    # key -> accepted values; AND across keys, OR within a key's values
    labels: dict[str, list[str]] = field(default_factory=dict)
    deleted: bool = False
    limit: int = 20
    offset: int = 0
    sort_by: str = "createdAt"
    sort_direction: str = "desc"


async def create(db: AsyncSession, **values: Any) -> Agent:
    agent = Agent(**values)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def get(
    db: AsyncSession, agent_id: uuid.UUID, *, where: ColumnElement[bool] | None = None
) -> Agent | None:
    stmt = select(Agent).where(Agent.id == agent_id)
    if where is not None:
        stmt = stmt.where(where)
    return await db.scalar(stmt)


async def list_paginated(
    db: AsyncSession, filters: AgentListFilters, *, visibility: ColumnElement[bool]
) -> tuple[list[Agent], int]:
    conds = [visibility, *_filter_conditions(filters)]
    total = await db.scalar(select(func.count()).select_from(Agent).where(*conds)) or 0
    stmt = (
        select(Agent)
        .where(*conds)
        .order_by(*_order_by(filters.sort_by, filters.sort_direction))
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return list(await db.scalars(stmt)), total


async def list_all_visible(db: AsyncSession, *, visibility: ColumnElement[bool]) -> list[Agent]:
    stmt = select(Agent).where(visibility, Agent.deleted_at.is_(None)).order_by(Agent.name)
    return list(await db.scalars(stmt))


async def update_fields(db: AsyncSession, agent: Agent, values: dict[str, Any]) -> Agent:
    for key, value in values.items():
        setattr(agent, key, value)
    agent.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(agent)
    return agent


async def soft_delete(db: AsyncSession, agent: Agent) -> None:
    agent.deleted_at = datetime.now(UTC)
    # Clear default-agent pins pointing at the deleted agent (Archestra does the same).
    await db.execute(
        update(MemberSettings)
        .where(MemberSettings.default_agent_id == agent.id)
        .values(default_agent_id=None)
    )
    await db.flush()


async def restore(db: AsyncSession, agent: Agent) -> None:
    agent.deleted_at = None
    await db.flush()
    # updated_at has a server-side onupdate; reload it so it is readable after flush.
    await db.refresh(agent)


async def purge(db: AsyncSession, agent: Agent) -> None:
    """Hard delete; team/user/label links cascade, default pins are SET NULL."""
    await db.execute(delete(Agent).where(Agent.id == agent.id))
    await db.flush()


async def active_name_exists(
    db: AsyncSession, name: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    conds = [Agent.name == name, Agent.deleted_at.is_(None)]
    if exclude_id is not None:
        conds.append(Agent.id != exclude_id)
    return bool(await db.scalar(select(exists().where(*conds))))


# =============================================================================
# Internal helpers
# =============================================================================


def _filter_conditions(filters: AgentListFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [
        Agent.deleted_at.is_not(None) if filters.deleted else Agent.deleted_at.is_(None)
    ]
    if filters.name:
        conds.append(Agent.name.ilike(f"%{_escape_like(filters.name)}%", escape="\\"))
    if filters.agent_type:
        conds.append(Agent.agent_type == filters.agent_type)
    if filters.scope:
        conds.append(Agent.scope == filters.scope)
    if filters.team_ids:
        conds.append(
            exists(
                select(1).where(
                    AgentTeam.agent_id == Agent.id, AgentTeam.team_id.in_(filters.team_ids)
                )
            )
        )
    for key, values in filters.labels.items():
        conds.append(
            exists(
                select(1)
                .select_from(AgentLabel)
                .join(LabelKey, LabelKey.id == AgentLabel.key_id)
                .join(LabelValue, LabelValue.id == AgentLabel.value_id)
                .where(
                    AgentLabel.agent_id == Agent.id,
                    LabelKey.key == key,
                    LabelValue.value.in_(values),
                )
            )
        )
    return conds


def _order_by(sort_by: str, direction: str) -> list[Any]:
    if sort_by == "name":
        column: Any = func.lower(Agent.name)
    elif sort_by == "team":
        column = (
            select(func.min(Team.name))
            .join(AgentTeam, AgentTeam.team_id == Team.id)
            .where(AgentTeam.agent_id == Agent.id)
            .scalar_subquery()
        )
    else:
        column = Agent.created_at
    primary = column.asc().nulls_last() if direction == "asc" else column.desc().nulls_last()
    return [primary, Agent.id]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
