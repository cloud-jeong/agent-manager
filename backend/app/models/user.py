import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'member')", name="role"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Organization-wide role. `admin` sees and manages every agent.
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member", server_default="member"
    )
    created_at: Mapped[datetime] = created_at_col()


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (CheckConstraint("role IN ('member', 'team_admin')", name="role"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # `team_admin` may create and manage team-scoped agents of this team.
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member", server_default="member"
    )
    created_at: Mapped[datetime] = created_at_col()


class MemberSettings(Base):
    """Per-user preferences (Archestra's `member.default_agent_id`)."""

    __tablename__ = "member_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    default_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")
    )
