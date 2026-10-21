import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentActor, DbSession
from app.schemas.common import Paginated, SuccessResponse
from app.schemas.runtime import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    SendMessageResponse,
)
from app.services import conversation as conversation_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=Paginated[ConversationRead], operation_id="listConversations")
async def list_conversations(
    actor: CurrentActor,
    db: DbSession,
    agent_id: uuid.UUID | None = Query(default=None, alias="agentId"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Paginated[ConversationRead]:
    return await conversation_service.list_conversations(
        db, actor, agent_id=agent_id, limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createConversation",
)
async def create_conversation(
    body: ConversationCreate, actor: CurrentActor, db: DbSession
) -> ConversationRead:
    return await conversation_service.create_conversation(
        db, actor, agent_id=body.agent_id, title=body.title
    )


@router.get("/{conversation_id}", response_model=ConversationDetail, operation_id="getConversation")
async def get_conversation(
    conversation_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ConversationDetail:
    return await conversation_service.get_conversation(db, actor, conversation_id)


@router.patch(
    "/{conversation_id}", response_model=ConversationRead, operation_id="updateConversation"
)
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, actor: CurrentActor, db: DbSession
) -> ConversationRead:
    return await conversation_service.rename_conversation(db, actor, conversation_id, body.title)


@router.delete(
    "/{conversation_id}", response_model=SuccessResponse, operation_id="deleteConversation"
)
async def delete_conversation(
    conversation_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> SuccessResponse:
    await conversation_service.delete_conversation(db, actor, conversation_id)
    return SuccessResponse()


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="sendMessage",
)
async def send_message(
    conversation_id: uuid.UUID, body: MessageCreate, actor: CurrentActor, db: DbSession
) -> SendMessageResponse:
    """Store the user's message and queue a run; follow it via `/api/runs/{id}/events`."""
    return await conversation_service.send_message(db, actor, conversation_id, body.content)
