"""Remote MCP servers that agents can use. Admins manage them; everyone can list them."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import AdminActor, CurrentActor, DbSession
from app.crypto import encrypt
from app.errors import ApiError
from app.models import McpServer
from app.repositories import mcp_server as mcp_server_repo
from app.schemas.common import SuccessResponse
from app.schemas.runtime import McpServerCreate, McpServerRead, McpServerUpdate

router = APIRouter(prefix="/api/mcp-servers", tags=["mcp-servers"])


@router.get("", response_model=list[McpServerRead], operation_id="listMcpServers")
async def list_mcp_servers(_: CurrentActor, db: DbSession) -> list[McpServerRead]:
    return [to_read(s) for s in await mcp_server_repo.list_all(db)]


@router.post(
    "",
    response_model=McpServerRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createMcpServer",
)
async def create_mcp_server(body: McpServerCreate, _: AdminActor, db: DbSession) -> McpServerRead:
    _require_https(str(body.url))
    if await mcp_server_repo.get_by_name(db, body.name):
        raise ApiError(409, "An MCP server with this name already exists")
    server = await mcp_server_repo.create(
        db,
        name=body.name,
        url=str(body.url),
        description=body.description,
        token_encrypted=encrypt(body.token) if body.token else None,
    )
    await db.commit()
    return to_read(server)


@router.put("/{server_id}", response_model=McpServerRead, operation_id="updateMcpServer")
async def update_mcp_server(
    server_id: uuid.UUID, body: McpServerUpdate, _: AdminActor, db: DbSession
) -> McpServerRead:
    server = await _get(db, server_id)
    data = body.model_dump(exclude_unset=True)
    values: dict[str, object] = {}
    if data.get("name") is not None and data["name"] != server.name:
        if await mcp_server_repo.get_by_name(db, data["name"]):
            raise ApiError(409, "An MCP server with this name already exists")
        values["name"] = data["name"]
    if data.get("url") is not None:
        _require_https(str(data["url"]))
        values["url"] = str(data["url"])
    if "description" in data:
        values["description"] = data["description"]
    if "token" in data:
        values["token_encrypted"] = encrypt(data["token"]) if data["token"] else None
    await mcp_server_repo.update_fields(db, server, values)
    await db.commit()
    return to_read(server)


@router.delete("/{server_id}", response_model=SuccessResponse, operation_id="deleteMcpServer")
async def delete_mcp_server(server_id: uuid.UUID, _: AdminActor, db: DbSession) -> SuccessResponse:
    """Also detaches the server from every agent using it."""
    await mcp_server_repo.delete_server(db, await _get(db, server_id))
    await db.commit()
    return SuccessResponse()


def to_read(server: McpServer) -> McpServerRead:
    return McpServerRead(
        id=server.id,
        name=server.name,
        url=server.url,
        description=server.description,
        has_token=server.token_encrypted is not None,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


async def _get(db: DbSession, server_id: uuid.UUID) -> McpServer:
    server = await mcp_server_repo.get(db, server_id)
    if server is None:
        raise ApiError(404, "MCP server not found")
    return server


def _require_https(url: str) -> None:
    # Claude connects from Anthropic's servers, so the URL must be publicly reachable over TLS.
    if not url.startswith("https://"):
        raise ApiError(400, "MCP server URLs must use https://")
