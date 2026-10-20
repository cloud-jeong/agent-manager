import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class LabelKey(Base):
    __tablename__ = "label_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class LabelValue(Base):
    __tablename__ = "label_values"

    id: Mapped[uuid.UUID] = uuid_pk()
    value: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class AgentLabel(Base):
    """One value per key per agent (PK is agent_id + key_id)."""

    __tablename__ = "agent_labels"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("label_keys.id", ondelete="CASCADE"), primary_key=True
    )
    value_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("label_values.id", ondelete="CASCADE"), nullable=False
    )
