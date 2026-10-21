import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.common import CamelModel

AgentScope = Literal["personal", "team", "org"]
AgentType = Literal["agent", "mcp_gateway"]
AgentShareLevel = Literal["use", "write"]
AgentStatus = Literal["active", "deleted"]
AgentSortBy = Literal["name", "createdAt", "team"]
SortDirection = Literal["asc", "desc"]
AgentModel = Literal["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
AgentEffort = Literal["low", "medium", "high", "xhigh", "max"]


class AgentLabelIn(CamelModel):
    model_config = ConfigDict(**CamelModel.model_config, str_strip_whitespace=True)

    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=200)


class AgentUserShareIn(CamelModel):
    user_id: uuid.UUID
    level: AgentShareLevel = "use"


class AgentTools(CamelModel):
    """Tools the agent may call at runtime. Stored as snake_case JSON on the agent row."""

    bash: bool = False
    text_editor: bool = False
    web_search: bool = False
    web_fetch: bool = False


class _AgentWritable(CamelModel):
    @field_validator("labels", check_fields=False)
    @classmethod
    def _unique_label_keys(cls, labels: list[AgentLabelIn] | None) -> list[AgentLabelIn] | None:
        if labels is not None:
            keys = [label.key for label in labels]
            if len(keys) != len(set(keys)):
                raise ValueError("label keys must be unique")
        return labels


class AgentCreate(_AgentWritable):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    icon: str | None = Field(default=None, max_length=32)
    agent_type: AgentType = "agent"
    scope: AgentScope = "personal"
    consider_context_untrusted: bool = False
    model: AgentModel = "claude-opus-5-5"
    effort: AgentEffort = "medium"
    max_turns: int = Field(default=30, ge=1, le=200)
    tools: AgentTools = Field(default_factory=AgentTools)
    sandbox_network: bool = False
    mcp_servers: list[uuid.UUID] = Field(default_factory=list)
    teams: list[uuid.UUID] = Field(default_factory=list)
    users: list[AgentUserShareIn] = Field(default_factory=list)
    labels: list[AgentLabelIn] = Field(default_factory=list)


class AgentUpdate(_AgentWritable):
    """Partial update: omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    icon: str | None = Field(default=None, max_length=32)
    agent_type: AgentType | None = None
    scope: AgentScope | None = None
    consider_context_untrusted: bool | None = None
    model: AgentModel | None = None
    effort: AgentEffort | None = None
    max_turns: int | None = Field(default=None, ge=1, le=200)
    tools: AgentTools | None = None
    sandbox_network: bool | None = None
    mcp_servers: list[uuid.UUID] | None = None
    teams: list[uuid.UUID] | None = None
    users: list[AgentUserShareIn] | None = None
    labels: list[AgentLabelIn] | None = None


class AgentTeamRef(CamelModel):
    id: uuid.UUID
    name: str


class AgentUserRef(CamelModel):
    id: uuid.UUID
    name: str
    email: str
    level: AgentShareLevel


class AgentMcpServerRef(CamelModel):
    id: uuid.UUID
    name: str


class AgentLabelRead(CamelModel):
    key: str
    value: str


class AgentRead(CamelModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str | None
    icon: str | None
    agent_type: AgentType
    scope: AgentScope
    author_id: uuid.UUID | None
    author_name: str | None
    consider_context_untrusted: bool
    model: str
    effort: AgentEffort
    max_turns: int
    tools: AgentTools
    sandbox_network: bool
    mcp_servers: list[AgentMcpServerRef]
    teams: list[AgentTeamRef]
    users: list[AgentUserRef]
    labels: list[AgentLabelRead]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    # Whether the requesting user may edit/delete this agent.
    can_modify: bool
