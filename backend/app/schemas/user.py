import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field

from app.schemas.common import CamelModel

UserRole = Literal["admin", "member"]
TeamRole = Literal["member", "team_admin"]


class UserRead(CamelModel):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    created_at: datetime


class UserCreate(CamelModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: UserRole = "member"


class UserTeamMembership(CamelModel):
    id: uuid.UUID
    name: str
    role: TeamRole


class MeRead(UserRead):
    teams: list[UserTeamMembership]


class LoginRequest(CamelModel):
    email: str
    password: str


class LoginResponse(CamelModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: MeRead


class TeamMemberRead(CamelModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: TeamRole


class TeamRead(CamelModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    members: list[TeamMemberRead]


class TeamCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class TeamUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class TeamMemberUpsert(CamelModel):
    role: TeamRole = "member"


class DefaultAgentRead(CamelModel):
    default_agent_id: uuid.UUID | None


class DefaultAgentUpdate(CamelModel):
    default_agent_id: uuid.UUID | None
