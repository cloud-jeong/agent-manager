import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, updated_at_col, uuid_pk

DEFAULT_MODEL = "claude-opus-5-5"


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("scope IN ('personal', 'team', 'org')", name="scope"),
        CheckConstraint("agent_type IN ('agent', 'mcp_gateway')", name="agent_type"),
        CheckConstraint("effort IN ('low', 'medium', 'high', 'xhigh', 'max')", name="effort"),
        CheckConstraint("max_turns BETWEEN 1 AND 200", name="max_turns"),
        Index("ix_agents_scope", "scope"),
        Index("ix_agents_author_id", "author_id"),
        Index("ix_agents_agent_type", "agent_type"),
        Index("ix_agents_deleted_at", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Not unique, matching Archestra.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    # Emoji shown next to the name.
    icon: Mapped[str | None] = mapped_column(String(32))
    agent_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="agent", server_default="agent"
    )
    # personal: author + explicitly shared users; team: members of assigned teams; org: everyone
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="personal", server_default="personal"
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    consider_context_untrusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Runtime settings used when the agent is executed.
    model: Mapped[str] = mapped_column(
        String(100), nullable=False, default=DEFAULT_MODEL, server_default=DEFAULT_MODEL
    )
    effort: Mapped[str] = mapped_column(
        String(10), nullable=False, default="medium", server_default="medium"
    )
    # Upper bound on model requests per run (each tool round trip is one turn).
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    # Enabled tools: {"bash": bool, "text_editor": bool, "web_search": bool, "web_fetch": bool}
    tools: Mapped[dict[str, bool]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Whether the sandbox container gets network access.
    sandbox_network: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    # Soft delete marker; NULL means active.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentTeam(Base):
    __tablename__ = "agent_teams"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )


class AgentUser(Base):
    """Shares a personal agent with named users."""

    __tablename__ = "agent_users"
    __table_args__ = (CheckConstraint("level IN ('use', 'write')", name="level"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="use", server_default="use"
    )
