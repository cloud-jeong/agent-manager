"""Who can see and who can modify which agents.

Ported from Archestra:
- visibility: `AgentModel.findAccessibleIdsForUser` (models/agent.ts)
- modification: `requireAgentModifyPermission` (auth/agent-type-permissions.ts)
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, and_, exists, false, or_, select, true

from app.models import Agent, AgentTeam, AgentUser, User


@dataclass(frozen=True)
class Actor:
    """The authenticated user plus their team memberships (team_id -> role)."""

    user: User
    team_roles: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"

    @property
    def team_ids(self) -> set[uuid.UUID]:
        return set(self.team_roles)

    @property
    def admin_team_ids(self) -> set[uuid.UUID]:
        return {t for t, role in self.team_roles.items() if role == "team_admin"}


def visible_agents_clause(actor: Actor) -> ColumnElement[bool]:
    """Admins see everything. Others see org agents, team agents of their teams,
    and personal agents they authored or were shared with."""
    if actor.is_admin:
        return true()
    personal = and_(
        Agent.scope == "personal",
        or_(Agent.author_id == actor.id, _has_user_grant(actor.id)),
    )
    clauses = [Agent.scope == "org", personal]
    if actor.team_ids:
        clauses.append(and_(Agent.scope == "team", _has_any_team(actor.team_ids)))
    return or_(*clauses)


def modifiable_agents_clause(actor: Actor) -> ColumnElement[bool]:
    """SQL counterpart of `can_modify`; keep the two in sync."""
    if actor.is_admin:
        return true()
    personal = and_(
        Agent.scope == "personal",
        or_(Agent.author_id == actor.id, _has_user_grant(actor.id, level="write")),
    )
    team = (
        and_(Agent.scope == "team", _has_any_team(actor.admin_team_ids))
        if actor.admin_team_ids
        else false()
    )
    return or_(personal, team)


def can_modify(
    actor: Actor,
    *,
    agent: Agent,
    agent_team_ids: set[uuid.UUID],
    write_grant_user_ids: set[uuid.UUID],
) -> bool:
    """Admins: always. org: admin only. team: team_admin of one of the agent's teams.
    personal: the author or a user shared with `write` level."""
    if actor.is_admin:
        return True
    if agent.scope == "org":
        return False
    if agent.scope == "team":
        return bool(agent_team_ids & actor.admin_team_ids)
    return agent.author_id == actor.id or actor.id in write_grant_user_ids


# =============================================================================
# Internal helpers
# =============================================================================


def _has_user_grant(user_id: uuid.UUID, level: str | None = None) -> ColumnElement[bool]:
    conds = [AgentUser.agent_id == Agent.id, AgentUser.user_id == user_id]
    if level is not None:
        conds.append(AgentUser.level == level)
    return exists(select(1).where(*conds))


def _has_any_team(team_ids: set[uuid.UUID]) -> ColumnElement[bool]:
    return exists(select(1).where(AgentTeam.agent_id == Agent.id, AgentTeam.team_id.in_(team_ids)))
