import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field

from app.schemas.common import CamelModel

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RunTrigger = Literal["chat", "api"]
MessageRole = Literal["user", "assistant"]

# Statuses after which a run never changes again.
TERMINAL_RUN_STATUSES = ("succeeded", "failed", "cancelled")


class ConversationCreate(CamelModel):
    agent_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(CamelModel):
    title: str = Field(min_length=1, max_length=200)


class MessageCreate(CamelModel):
    content: str = Field(min_length=1, max_length=100_000)


class RunCreate(CamelModel):
    input: str = Field(min_length=1, max_length=100_000)


class AgentRef(CamelModel):
    id: uuid.UUID
    name: str
    icon: str | None


class RunRead(CamelModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    agent: AgentRef
    trigger: RunTrigger
    status: RunStatus
    error: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(RunRead):
    # Text of the run's final assistant message, once it has one.
    output: str | None


class MessageRead(CamelModel):
    id: uuid.UUID
    seq: int
    role: MessageRole
    # Content blocks in Messages API shape (text, thinking, tool_use, tool_result, ...).
    content: list[dict[str, Any]]
    run_id: uuid.UUID | None
    created_at: datetime


class ConversationRead(CamelModel):
    id: uuid.UUID
    agent: AgentRef
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]
    # The queued or running run, if any; clients attach to its event stream.
    active_run: RunRead | None


class SendMessageResponse(CamelModel):
    message: MessageRead
    run: RunRead


# Sent to the API as the server's `name`.
_MCP_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class McpServerCreate(CamelModel):
    name: str = Field(pattern=_MCP_NAME_PATTERN)
    url: AnyHttpUrl
    description: str | None = None
    # Bearer token Claude sends to the server. Write-only: never returned by the API.
    token: str | None = Field(default=None, min_length=1, max_length=10_000)


class McpServerUpdate(CamelModel):
    """Partial update. `token: null` removes the token; omit it to keep the current one."""

    name: str | None = Field(default=None, pattern=_MCP_NAME_PATTERN)
    url: AnyHttpUrl | None = None
    description: str | None = None
    token: str | None = Field(default=None, min_length=1, max_length=10_000)


class McpServerRead(CamelModel):
    id: uuid.UUID
    name: str
    url: str
    description: str | None
    has_token: bool
    created_at: datetime
    updated_at: datetime
