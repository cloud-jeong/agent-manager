from fastapi import APIRouter, status

from app.api.deps import AdminActor, CurrentActor, DbSession
from app.errors import ApiError
from app.repositories import user as user_repo
from app.schemas.user import UserCreate, UserRead
from app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserRead], operation_id="listUsers")
async def list_users(_: CurrentActor, db: DbSession) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in await user_repo.list_all(db)]


@router.post(
    "", response_model=UserRead, status_code=status.HTTP_201_CREATED, operation_id="createUser"
)
async def create_user(body: UserCreate, _: AdminActor, db: DbSession) -> UserRead:
    if await user_repo.get_by_email(db, body.email):
        raise ApiError(409, "A user with this email already exists")
    user = await user_repo.create(
        db,
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    await db.commit()
    await db.refresh(user)
    return UserRead.model_validate(user)
