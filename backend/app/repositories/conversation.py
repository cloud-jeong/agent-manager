import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message


async def create(
    db: AsyncSession, *, agent_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> Conversation:
    conversation = Conversation(agent_id=agent_id, user_id=user_id, title=title)
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_owned(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation | None:
    return await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )


async def list_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[Conversation], int]:
    conds = [Conversation.user_id == user_id]
    if agent_id is not None:
        conds.append(Conversation.agent_id == agent_id)
    total = await db.scalar(select(func.count()).select_from(Conversation).where(*conds)) or 0
    stmt = (
        select(Conversation)
        .where(*conds)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    )
    return list(await db.scalars(stmt)), total


async def rename(db: AsyncSession, conversation: Conversation, title: str) -> None:
    conversation.title = title
    conversation.updated_at = datetime.now(UTC)
    await db.flush()


async def touch(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(UTC))
    )


async def set_sandbox(
    db: AsyncSession, conversation_id: uuid.UUID, container_id: str | None
) -> None:
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(sandbox_container_id=container_id)
    )


async def delete_conversation(db: AsyncSession, conversation: Conversation) -> None:
    await db.execute(delete(Conversation).where(Conversation.id == conversation.id))


async def existing_ids(db: AsyncSession, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(await db.scalars(select(Conversation.id).where(Conversation.id.in_(ids))))


# =============================================================================
# Messages
# =============================================================================


async def list_messages(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    return list(await db.scalars(stmt))


async def append_message(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: list[dict[str, Any]],
    run_id: uuid.UUID | None = None,
) -> Message:
    """Append at the next seq. The unique (conversation_id, seq) index rejects races."""
    next_seq = await db.scalar(
        select(func.coalesce(func.max(Message.seq) + 1, 0)).where(
            Message.conversation_id == conversation_id
        )
    )
    message = Message(
        conversation_id=conversation_id, seq=next_seq, role=role, content=content, run_id=run_id
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def get_last_message(db: AsyncSession, conversation_id: uuid.UUID) -> Message | None:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_last_assistant_messages(
    db: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Message]:
    """The latest assistant message produced by each run."""
    if not run_ids:
        return {}
    stmt = (
        select(Message)
        .where(Message.run_id.in_(run_ids), Message.role == "assistant")
        .order_by(Message.run_id, Message.seq.desc())
        .ext(distinct_on(Message.run_id))
    )
    return {m.run_id: m for m in await db.scalars(stmt) if m.run_id is not None}
