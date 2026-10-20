import uuid

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminActor, CurrentActor, DbSession
from app.errors import ApiError
from app.models import Team
from app.repositories import team as team_repo
from app.repositories import user as user_repo
from app.schemas.common import SuccessResponse
from app.schemas.user import TeamCreate, TeamMemberRead, TeamMemberUpsert, TeamRead, TeamUpdate

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=list[TeamRead], operation_id="listTeams")
async def list_teams(_: CurrentActor, db: DbSession) -> list[TeamRead]:
    return await _to_read(db, await team_repo.list_all(db))


@router.post(
    "", response_model=TeamRead, status_code=status.HTTP_201_CREATED, operation_id="createTeam"
)
async def create_team(body: TeamCreate, _: AdminActor, db: DbSession) -> TeamRead:
    if await team_repo.get_by_name(db, body.name):
        raise ApiError(409, "A team with this name already exists")
    team = await team_repo.create(db, name=body.name, description=body.description)
    await db.commit()
    return (await _to_read(db, [team]))[0]


@router.put("/{team_id}", response_model=TeamRead, operation_id="updateTeam")
async def update_team(
    team_id: uuid.UUID, body: TeamUpdate, _: AdminActor, db: DbSession
) -> TeamRead:
    team = await _get_team(db, team_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") and data["name"] != team.name:
        if await team_repo.get_by_name(db, data["name"]):
            raise ApiError(409, "A team with this name already exists")
        team.name = data["name"]
    if "description" in data:
        team.description = data["description"]
    await db.commit()
    return (await _to_read(db, [team]))[0]


@router.delete("/{team_id}", response_model=SuccessResponse, operation_id="deleteTeam")
async def delete_team(team_id: uuid.UUID, _: AdminActor, db: DbSession) -> SuccessResponse:
    await team_repo.delete_team(db, await _get_team(db, team_id))
    await db.commit()
    return SuccessResponse()


@router.put(
    "/{team_id}/members/{user_id}", response_model=TeamRead, operation_id="upsertTeamMember"
)
async def upsert_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, body: TeamMemberUpsert, _: AdminActor, db: DbSession
) -> TeamRead:
    team = await _get_team(db, team_id)
    if await user_repo.get_by_id(db, user_id) is None:
        raise ApiError(404, "User not found")
    await team_repo.upsert_member(db, team_id=team_id, user_id=user_id, role=body.role)
    await db.commit()
    return (await _to_read(db, [team]))[0]


@router.delete(
    "/{team_id}/members/{user_id}", response_model=TeamRead, operation_id="removeTeamMember"
)
async def remove_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, _: AdminActor, db: DbSession
) -> TeamRead:
    team = await _get_team(db, team_id)
    if not await team_repo.remove_member(db, team_id=team_id, user_id=user_id):
        raise ApiError(404, "User is not a member of this team")
    await db.commit()
    return (await _to_read(db, [team]))[0]


async def _get_team(db: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await team_repo.get(db, team_id)
    if team is None:
        raise ApiError(404, "Team not found")
    return team


async def _to_read(db: AsyncSession, teams: list[Team]) -> list[TeamRead]:
    members = await team_repo.get_members_for_teams(db, (t.id for t in teams))
    return [
        TeamRead(
            id=t.id,
            name=t.name,
            description=t.description,
            created_at=t.created_at,
            members=[
                TeamMemberRead(user_id=u, name=n, email=e, role=r) for u, n, e, r in members[t.id]
            ],
        )
        for t in teams
    ]
