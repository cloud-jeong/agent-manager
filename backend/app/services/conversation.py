"""Conversations and the runs started from them.

Running an agent requires being able to see it (the same rule as reading it).
Conversations and runs are private: other users get 404, as for invisible agents.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Agent, Conversation, Message, Run
from app.repositories import conversation as conversation_repo
from app.repositories import run as run_repo
from app.repositories import run_event as run_event_repo
from app.repositories.run import RunListFilters
from app.schemas.common import Paginated, Pagination
from app.schemas.runtime import (
    AgentRef,
    ConversationDetail,
    ConversationRead,
    MessageRead,
    RunDetail,
    RunRead,
    SendMessageResponse,
)
from app.services import agent as agent_service
from app.services.access import Actor

DEFAULT_TITLE = "New conversation"
_TITLE_LENGTH = 60


async def create_conversation(
    db: AsyncSession, actor: Actor, *, agent_id: uuid.UUID, title: str | None
) -> ConversationRead:
    agent = await get_runnable_agent(db, actor, agent_id)
    conversation = await conversation_repo.create(
        db, agent_id=agent.id, user_id=actor.id, title=(title or "").strip() or DEFAULT_TITLE
    )
    await db.commit()
    return (await _hydrate_conversations(db, [conversation]))[0]


async def list_conversations(
    db: AsyncSession, actor: Actor, *, agent_id: uuid.UUID | None, limit: int, offset: int
) -> Paginated[ConversationRead]:
    conversations, total = await conversation_repo.list_for_user(
        db, actor.id, agent_id=agent_id, limit=limit, offset=offset
    )
    return Paginated[ConversationRead](
        data=await _hydrate_conversations(db, conversations),
        pagination=Pagination(
            total=total, limit=limit, offset=offset, has_next=offset + len(conversations) < total
        ),
    )


async def get_conversation(
    db: AsyncSession, actor: Actor, conversation_id: uuid.UUID
) -> ConversationDetail:
    conversation = await get_owned_conversation(db, actor, conversation_id)
    base = (await _hydrate_conversations(db, [conversation]))[0]
    messages = await conversation_repo.list_messages(db, conversation.id)
    active = (await run_repo.get_active_for_conversations(db, [conversation.id])).get(
        conversation.id
    )
    return ConversationDetail(
        **base.model_dump(),
        messages=[MessageRead.model_validate(m) for m in messages],
        active_run=(await hydrate_runs(db, [active]))[0] if active else None,
    )


async def rename_conversation(
    db: AsyncSession, actor: Actor, conversation_id: uuid.UUID, title: str
) -> ConversationRead:
    conversation = await get_owned_conversation(db, actor, conversation_id)
    await conversation_repo.rename(db, conversation, title.strip())
    await db.commit()
    return (await _hydrate_conversations(db, [conversation]))[0]


async def delete_conversation(db: AsyncSession, actor: Actor, conversation_id: uuid.UUID) -> None:
    """Deletes messages and runs too. The worker removes the sandbox container later."""
    conversation = await get_owned_conversation(db, actor, conversation_id)
    if (await run_repo.get_active_for_conversations(db, [conversation.id])).get(conversation.id):
        raise ApiError(409, "Stop the running response before deleting the conversation")
    await conversation_repo.delete_conversation(db, conversation)
    await db.commit()


async def send_message(
    db: AsyncSession, actor: Actor, conversation_id: uuid.UUID, content: str
) -> SendMessageResponse:
    conversation = await get_owned_conversation(db, actor, conversation_id)
    # The agent may have been deleted or hidden from the user since the chat started.
    await get_runnable_agent(db, actor, conversation.agent_id)
    message, run = await _enqueue(db, actor, conversation, content, trigger="chat")
    return SendMessageResponse(
        message=MessageRead.model_validate(message), run=(await hydrate_runs(db, [run]))[0]
    )


# =============================================================================
# Runs
# =============================================================================


async def start_run(db: AsyncSession, actor: Actor, agent_id: uuid.UUID, input_: str) -> RunRead:
    """Run an agent on one input in a new conversation (asynchronous API)."""
    agent = await get_runnable_agent(db, actor, agent_id)
    conversation = await conversation_repo.create(
        db, agent_id=agent.id, user_id=actor.id, title=_title_from(input_)
    )
    _, run = await _enqueue(db, actor, conversation, input_, trigger="api")
    return (await hydrate_runs(db, [run]))[0]


async def list_runs(db: AsyncSession, actor: Actor, filters: RunListFilters) -> Paginated[RunRead]:
    runs, total = await run_repo.list_for_user(db, actor.id, filters)
    return Paginated[RunRead](
        data=await hydrate_runs(db, runs),
        pagination=Pagination(
            total=total,
            limit=filters.limit,
            offset=filters.offset,
            has_next=filters.offset + len(runs) < total,
        ),
    )


async def get_run(db: AsyncSession, actor: Actor, run_id: uuid.UUID) -> RunDetail:
    run = await get_owned_run(db, actor, run_id)
    last = (await conversation_repo.get_last_assistant_messages(db, [run.id])).get(run.id)
    return RunDetail(
        **(await hydrate_runs(db, [run]))[0].model_dump(),
        output=_text_of(last) if last else None,
    )


async def cancel_run(db: AsyncSession, actor: Actor, run_id: uuid.UUID) -> RunRead:
    run = await get_owned_run(db, actor, run_id)
    if run.status not in ("queued", "running"):
        raise ApiError(409, "The run has already finished")
    was_queued = run.status == "queued"
    await run_repo.request_cancel(db, run)
    if was_queued:
        # No worker owns it, so finish it here (a running run is finished by its worker).
        await run_event_repo.append(
            db, run.id, [(0, "run_finished", {"status": "cancelled", "error": None})]
        )
    await db.commit()
    return (await hydrate_runs(db, [run]))[0]


async def get_owned_run(db: AsyncSession, actor: Actor, run_id: uuid.UUID) -> Run:
    run = await run_repo.get_owned(db, run_id, actor.id)
    if run is None:
        raise ApiError(404, "Run not found")
    return run


async def hydrate_runs(db: AsyncSession, runs: list[Run]) -> list[RunRead]:
    agents = await _agent_refs(db, {r.agent_id for r in runs})
    return [
        RunRead(
            id=r.id,
            conversation_id=r.conversation_id,
            agent=agents[r.agent_id],
            trigger=r.trigger,
            status=r.status,
            error=r.error,
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cache_read_input_tokens=r.cache_read_input_tokens,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in runs
    ]


# =============================================================================
# Shared helpers
# =============================================================================


async def get_runnable_agent(db: AsyncSession, actor: Actor, agent_id: uuid.UUID) -> Agent:
    agent = await agent_service.get_visible_active_agent(db, actor, agent_id)
    if agent.agent_type != "agent":
        raise ApiError(400, "Only agents of type 'agent' can be run")
    return agent


async def get_owned_conversation(
    db: AsyncSession, actor: Actor, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await conversation_repo.get_owned(db, conversation_id, actor.id)
    if conversation is None:
        raise ApiError(404, "Conversation not found")
    return conversation


async def _enqueue(
    db: AsyncSession, actor: Actor, conversation: Conversation, content: str, *, trigger: str
) -> tuple[Message, Run]:
    if (await run_repo.get_active_for_conversations(db, [conversation.id])).get(conversation.id):
        raise ApiError(409, "The agent is still responding in this conversation")
    is_first = await conversation_repo.get_last_message(db, conversation.id) is None
    try:
        message = await conversation_repo.append_message(
            db,
            conversation_id=conversation.id,
            role="user",
            content=[{"type": "text", "text": content}],
        )
        run = await run_repo.create(
            db,
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            user_id=actor.id,
            trigger=trigger,
        )
    except IntegrityError as exc:
        # Lost a race with another message on the same conversation.
        await db.rollback()
        raise ApiError(409, "The agent is still responding in this conversation") from exc
    if is_first and conversation.title == DEFAULT_TITLE:
        await conversation_repo.rename(db, conversation, _title_from(content))
    else:
        await conversation_repo.touch(db, conversation.id)
    await db.commit()
    await db.refresh(message)
    await db.refresh(run)
    return message, run


async def _hydrate_conversations(
    db: AsyncSession, conversations: list[Conversation]
) -> list[ConversationRead]:
    agents = await _agent_refs(db, {c.agent_id for c in conversations})
    return [
        ConversationRead(
            id=c.id,
            agent=agents[c.agent_id],
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


async def _agent_refs(db: AsyncSession, agent_ids: set[uuid.UUID]) -> dict[uuid.UUID, AgentRef]:
    if not agent_ids:
        return {}
    rows = await db.execute(select(Agent.id, Agent.name, Agent.icon).where(Agent.id.in_(agent_ids)))
    return {id_: AgentRef(id=id_, name=name, icon=icon) for id_, name, icon in rows}


def _title_from(content: str) -> str:
    line = " ".join(content.split())
    return line if len(line) <= _TITLE_LENGTH else line[: _TITLE_LENGTH - 1] + "…"


def _text_of(message: Message) -> str:
    return "\n\n".join(b["text"] for b in message.content if b.get("type") == "text")
