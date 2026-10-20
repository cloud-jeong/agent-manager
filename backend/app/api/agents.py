import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentActor, DbSession
from app.errors import ApiError
from app.repositories import label as label_repo
from app.repositories.agent import AgentListFilters
from app.schemas.agent import (
    AgentCreate,
    AgentRead,
    AgentScope,
    AgentSortBy,
    AgentStatus,
    AgentType,
    AgentUpdate,
    SortDirection,
)
from app.schemas.common import Paginated, SuccessResponse
from app.services import agent as agent_service

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=Paginated[AgentRead], operation_id="listAgents")
async def list_agents(
    actor: CurrentActor,
    db: DbSession,
    name: str | None = Query(default=None, description="Case-insensitive substring match"),
    agent_type: AgentType | None = Query(default=None, alias="agentType"),
    scope: AgentScope | None = None,
    team_ids: str | None = Query(
        default=None, alias="teamIds", description="Comma-separated team ids"
    ),
    labels: str | None = Query(
        default=None,
        description="`key1:v1|v2;key2:v3` - AND across keys, OR within a key's values",
    ),
    agent_status: AgentStatus = Query(default="active", alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: AgentSortBy = Query(default="createdAt", alias="sortBy"),
    sort_direction: SortDirection = Query(default="desc", alias="sortDirection"),
) -> Paginated[AgentRead]:
    filters = AgentListFilters(
        name=name.strip() if name else None,
        agent_type=agent_type,
        scope=scope,
        team_ids=_parse_team_ids(team_ids),
        labels=_parse_label_filter(labels),
        deleted=agent_status == "deleted",
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
    return await agent_service.list_agents(db, actor, filters)


@router.get("/all", response_model=list[AgentRead], operation_id="listAllAgents")
async def list_all_agents(actor: CurrentActor, db: DbSession) -> list[AgentRead]:
    """Every active agent visible to the caller (unpaginated, for pickers)."""
    return await agent_service.list_all_visible(db, actor)


@router.get("/labels/keys", response_model=list[str], operation_id="listAgentLabelKeys")
async def list_label_keys(_: CurrentActor, db: DbSession) -> list[str]:
    return await label_repo.get_all_keys(db)


@router.get("/labels/values", response_model=list[str], operation_id="listAgentLabelValues")
async def list_label_values(_: CurrentActor, db: DbSession, key: str | None = None) -> list[str]:
    return await label_repo.get_values(db, key)


@router.post(
    "", response_model=AgentRead, status_code=status.HTTP_201_CREATED, operation_id="createAgent"
)
async def create_agent(body: AgentCreate, actor: CurrentActor, db: DbSession) -> AgentRead:
    return await agent_service.create_agent(db, actor, body)


@router.get("/{agent_id}", response_model=AgentRead, operation_id="getAgent")
async def get_agent(agent_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> AgentRead:
    return await agent_service.get_agent(db, actor, agent_id)


@router.put("/{agent_id}", response_model=AgentRead, operation_id="updateAgent")
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, actor: CurrentActor, db: DbSession
) -> AgentRead:
    return await agent_service.update_agent(db, actor, agent_id, body)


@router.delete("/{agent_id}", response_model=SuccessResponse, operation_id="deleteAgent")
async def delete_agent(agent_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> SuccessResponse:
    await agent_service.delete_agent(db, actor, agent_id)
    return SuccessResponse()


@router.post("/{agent_id}/restore", response_model=AgentRead, operation_id="restoreAgent")
async def restore_agent(agent_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> AgentRead:
    return await agent_service.restore_agent(db, actor, agent_id)


@router.delete("/{agent_id}/permanent", response_model=SuccessResponse, operation_id="purgeAgent")
async def purge_agent(agent_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> SuccessResponse:
    await agent_service.purge_agent(db, actor, agent_id)
    return SuccessResponse()


# =============================================================================
# Internal helpers
# =============================================================================


def _parse_team_ids(raw: str | None) -> list[uuid.UUID]:
    if not raw:
        return []
    try:
        return [uuid.UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise ApiError(400, "teamIds must be a comma-separated list of UUIDs") from exc


def _parse_label_filter(raw: str | None) -> dict[str, list[str]]:
    """Parse `key1:v1|v2;key2:v3` into {key1: [v1, v2], key2: [v3]}."""
    result: dict[str, list[str]] = {}
    if not raw:
        return result
    for part in raw.split(";"):
        if not part.strip():
            continue
        key, sep, values = part.partition(":")
        parsed = [v.strip() for v in values.split("|") if v.strip()]
        if not sep or not key.strip() or not parsed:
            raise ApiError(400, "labels must look like key1:v1|v2;key2:v3")
        result.setdefault(key.strip(), []).extend(parsed)
    return result
