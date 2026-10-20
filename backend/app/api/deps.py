from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import ApiError
from app.repositories import user as user_repo
from app.security import decode_access_token
from app.services.access import Actor

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_actor(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Actor:
    if credentials is None:
        raise ApiError(401, "Not authenticated")
    user_id = decode_access_token(credentials.credentials)
    user = await user_repo.get_by_id(db, user_id) if user_id else None
    if user is None:
        raise ApiError(401, "Invalid or expired token")
    memberships = await user_repo.get_team_memberships(db, user.id)
    return Actor(user=user, team_roles={team_id: role for team_id, _, role in memberships})


async def require_admin(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
    if not actor.is_admin:
        raise ApiError(403, "Admin permission required")
    return actor


CurrentActor = Annotated[Actor, Depends(get_actor)]
AdminActor = Annotated[Actor, Depends(require_admin)]
