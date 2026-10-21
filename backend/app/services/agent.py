"""Agent business rules (ported from Archestra's routes/agent.ts + models/agent.ts)."""

import uuid

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Agent
from app.repositories import agent as agent_repo
from app.repositories import agent_team as agent_team_repo
from app.repositories import agent_user as agent_user_repo
from app.repositories import label as label_repo
from app.repositories import team as team_repo
from app.repositories import user as user_repo
from app.repositories.agent import AgentListFilters
from app.schemas.agent import (
    AgentCreate,
    AgentLabelIn,
    AgentLabelRead,
    AgentRead,
    AgentTeamRef,
    AgentTools,
    AgentUpdate,
    AgentUserRef,
    AgentUserShareIn,
)
from app.schemas.common import Paginated, Pagination
from app.services.access import (
    Actor,
    can_modify,
    modifiable_agents_clause,
    visible_agents_clause,
)


async def list_agents(
    db: AsyncSession, actor: Actor, filters: AgentListFilters
) -> Paginated[AgentRead]:
    # Deleted agents are only listed for users who could restore them.
    visibility = (
        modifiable_agents_clause(actor) if filters.deleted else visible_agents_clause(actor)
    )
    agents, total = await agent_repo.list_paginated(db, filters, visibility=visibility)
    return Paginated[AgentRead](
        data=await hydrate(db, actor, agents),
        pagination=Pagination(
            total=total,
            limit=filters.limit,
            offset=filters.offset,
            has_next=filters.offset + len(agents) < total,
        ),
    )


async def list_all_visible(db: AsyncSession, actor: Actor) -> list[AgentRead]:
    agents = await agent_repo.list_all_visible(db, visibility=visible_agents_clause(actor))
    return await hydrate(db, actor, agents)


async def get_agent(db: AsyncSession, actor: Actor, agent_id: uuid.UUID) -> AgentRead:
    agent = await agent_repo.get(
        db,
        agent_id,
        where=or_(
            and_(Agent.deleted_at.is_(None), visible_agents_clause(actor)),
            and_(Agent.deleted_at.is_not(None), modifiable_agents_clause(actor)),
        ),
    )
    if agent is None:
        raise ApiError(404, "Agent not found")
    return (await hydrate(db, actor, [agent]))[0]


async def create_agent(db: AsyncSession, actor: Actor, body: AgentCreate) -> AgentRead:
    if body.scope == "org" and not actor.is_admin:
        raise ApiError(403, "Only admins can create organization-wide agents")

    team_ids: set[uuid.UUID] = set()
    if body.scope == "team":
        team_ids = set(body.teams)
        await _validate_team_assignment(db, actor, requested=team_ids, current=set())

    shares: dict[uuid.UUID, str] = {}
    if body.scope == "personal":
        shares = await _validate_user_shares(db, body.users, author_id=actor.id)

    agent = await agent_repo.create(
        db,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        icon=body.icon,
        agent_type=body.agent_type,
        scope=body.scope,
        author_id=actor.id,
        consider_context_untrusted=body.consider_context_untrusted,
        model=body.model,
        effort=body.effort,
        max_turns=body.max_turns,
        tools=body.tools.model_dump(),
        sandbox_network=body.sandbox_network,
    )
    await agent_team_repo.sync(db, agent.id, team_ids)
    await agent_user_repo.sync(db, agent.id, shares)
    await label_repo.sync_agent_labels(db, agent.id, _label_pairs(body.labels))
    await db.commit()
    return (await hydrate(db, actor, [agent]))[0]


async def update_agent(
    db: AsyncSession, actor: Actor, agent_id: uuid.UUID, body: AgentUpdate
) -> AgentRead:
    agent = await _get_modifiable_active_agent(db, actor, agent_id)
    data = body.model_dump(exclude_unset=True)

    for key in _NON_NULLABLE_FIELDS:
        if key in data and data[key] is None:
            raise ApiError(400, f"{key} cannot be null")

    new_scope = data.get("scope", agent.scope)
    if agent.scope != "personal" and new_scope == "personal":
        raise ApiError(400, "A shared agent cannot be made personal again")
    if new_scope == "org" and agent.scope != "org" and not actor.is_admin:
        raise ApiError(403, "Only admins can make an agent organization-wide")

    current_team_ids = {
        t for t, _ in (await agent_team_repo.get_teams_for_agents(db, [agent.id]))[agent.id]
    }
    if new_scope == "team":
        requested = set(body.teams) if body.teams is not None else current_team_ids
        await _validate_team_assignment(db, actor, requested=requested, current=current_team_ids)
        await agent_team_repo.sync(db, agent.id, requested)
    elif current_team_ids:
        await agent_team_repo.sync(db, agent.id, set())

    if new_scope != "personal":
        await agent_user_repo.sync(db, agent.id, {})
    elif body.users is not None:
        shares = await _validate_user_shares(db, body.users, author_id=agent.author_id)
        await agent_user_repo.sync(db, agent.id, shares)

    if body.labels is not None:
        await label_repo.sync_agent_labels(db, agent.id, _label_pairs(body.labels))

    columns = {k: v for k, v in data.items() if k in _COLUMN_FIELDS}
    if body.tools is not None:
        columns["tools"] = body.tools.model_dump()
    await agent_repo.update_fields(db, agent, columns)
    await db.commit()
    return (await hydrate(db, actor, [agent]))[0]


async def delete_agent(db: AsyncSession, actor: Actor, agent_id: uuid.UUID) -> None:
    agent = await _get_modifiable_active_agent(db, actor, agent_id)
    await agent_repo.soft_delete(db, agent)
    await db.commit()


async def restore_agent(db: AsyncSession, actor: Actor, agent_id: uuid.UUID) -> AgentRead:
    agent = await agent_repo.get(
        db,
        agent_id,
        where=and_(Agent.deleted_at.is_not(None), modifiable_agents_clause(actor)),
    )
    if agent is None:
        raise ApiError(404, "Deleted agent not found")
    if await agent_repo.active_name_exists(db, agent.name, exclude_id=agent.id):
        raise ApiError(
            409, f'An active agent named "{agent.name}" already exists. Rename it first.'
        )
    await agent_repo.restore(db, agent)
    await db.commit()
    return (await hydrate(db, actor, [agent]))[0]


async def purge_agent(db: AsyncSession, actor: Actor, agent_id: uuid.UUID) -> None:
    agent = await agent_repo.get(db, agent_id, where=modifiable_agents_clause(actor))
    if agent is None:
        raise ApiError(404, "Agent not found")
    if agent.deleted_at is None:
        raise ApiError(400, "Delete the agent before deleting it permanently")
    await agent_repo.purge(db, agent)
    await label_repo.prune_orphans(db)
    await db.commit()


async def get_visible_active_agent(db: AsyncSession, actor: Actor, agent_id: uuid.UUID) -> Agent:
    agent = await agent_repo.get(
        db, agent_id, where=and_(Agent.deleted_at.is_(None), visible_agents_clause(actor))
    )
    if agent is None:
        raise ApiError(404, "Agent not found")
    return agent


async def hydrate(db: AsyncSession, actor: Actor, agents: list[Agent]) -> list[AgentRead]:
    """Attach teams, shared users, labels and author names using batch queries (no N+1)."""
    ids = [a.id for a in agents]
    teams = await agent_team_repo.get_teams_for_agents(db, ids)
    users = await agent_user_repo.get_users_for_agents(db, ids)
    labels = await label_repo.get_labels_for_agents(db, ids)
    authors = await user_repo.get_many(db, (a.author_id for a in agents if a.author_id))

    result = []
    for a in agents:
        agent_users = users[a.id]
        author = authors.get(a.author_id) if a.author_id else None
        result.append(
            AgentRead(
                id=a.id,
                name=a.name,
                description=a.description,
                system_prompt=a.system_prompt,
                icon=a.icon,
                agent_type=a.agent_type,
                scope=a.scope,
                author_id=a.author_id,
                author_name=author.name if author else None,
                consider_context_untrusted=a.consider_context_untrusted,
                model=a.model,
                effort=a.effort,
                max_turns=a.max_turns,
                tools=AgentTools.model_validate(a.tools),
                sandbox_network=a.sandbox_network,
                teams=[AgentTeamRef(id=t_id, name=t_name) for t_id, t_name in teams[a.id]],
                users=[
                    AgentUserRef(id=u_id, name=name, email=email, level=level)
                    for u_id, name, email, level in agent_users
                ],
                labels=[AgentLabelRead(key=k, value=v) for k, v in labels[a.id]],
                created_at=a.created_at,
                updated_at=a.updated_at,
                deleted_at=a.deleted_at,
                can_modify=can_modify(
                    actor,
                    agent=a,
                    agent_team_ids={t_id for t_id, _ in teams[a.id]},
                    write_grant_user_ids={u[0] for u in agent_users if u[3] == "write"},
                ),
            )
        )
    return result


# =============================================================================
# Internal helpers
# =============================================================================

_COLUMN_FIELDS = {
    "name",
    "description",
    "system_prompt",
    "icon",
    "agent_type",
    "scope",
    "consider_context_untrusted",
    "model",
    "effort",
    "max_turns",
    "sandbox_network",
}
_NON_NULLABLE_FIELDS = (
    "name",
    "agent_type",
    "scope",
    "consider_context_untrusted",
    "model",
    "effort",
    "max_turns",
    "tools",
    "sandbox_network",
)


async def _get_modifiable_active_agent(
    db: AsyncSession, actor: Actor, agent_id: uuid.UUID
) -> Agent:
    # Missing modify permission returns 404 (not 403) so existence is not leaked.
    agent = await agent_repo.get(
        db,
        agent_id,
        where=and_(
            Agent.deleted_at.is_(None),
            visible_agents_clause(actor),
            modifiable_agents_clause(actor),
        ),
    )
    if agent is None:
        raise ApiError(404, "Agent not found")
    return agent


async def _validate_team_assignment(
    db: AsyncSession, actor: Actor, *, requested: set[uuid.UUID], current: set[uuid.UUID]
) -> None:
    if not requested:
        raise ApiError(400, "Team-scoped agents need at least one team")
    missing = requested - await team_repo.existing_ids(db, requested)
    if missing:
        raise ApiError(400, f"Unknown team(s): {', '.join(sorted(map(str, missing)))}")
    if actor.is_admin:
        return
    # Non-admins may only add or remove teams they administer; other teams are kept as-is.
    changed = requested ^ current
    if changed - actor.admin_team_ids:
        raise ApiError(403, "You can only assign agents to teams you administer")


async def _validate_user_shares(
    db: AsyncSession, shares: list[AgentUserShareIn], *, author_id: uuid.UUID | None
) -> dict[uuid.UUID, str]:
    result = {s.user_id: s.level for s in shares if s.user_id != author_id}
    missing = set(result) - set(await user_repo.get_many(db, result))
    if missing:
        raise ApiError(400, f"Unknown user(s): {', '.join(sorted(map(str, missing)))}")
    return result


def _label_pairs(labels: list[AgentLabelIn]) -> list[tuple[str, str]]:
    return [(label.key, label.value) for label in labels]
