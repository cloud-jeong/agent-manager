from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, DbSession
from app.errors import ApiError
from app.models import User
from app.repositories import user as user_repo
from app.schemas.user import LoginRequest, LoginResponse, MeRead, UserTeamMembership
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, operation_id="login")
async def login(body: LoginRequest, db: DbSession) -> LoginResponse:
    user = await user_repo.get_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "Invalid email or password")
    return LoginResponse(access_token=create_access_token(user.id), user=await _me(db, user))


@router.get("/me", response_model=MeRead, operation_id="getMe")
async def me(actor: CurrentActor, db: DbSession) -> MeRead:
    return await _me(db, actor.user)


async def _me(db: AsyncSession, user: User) -> MeRead:
    memberships = await user_repo.get_team_memberships(db, user.id)
    return MeRead(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        created_at=user.created_at,
        teams=[UserTeamMembership(id=t, name=n, role=r) for t, n, r in memberships],
    )
