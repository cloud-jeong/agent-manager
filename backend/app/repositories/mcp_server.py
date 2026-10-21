import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMcpServer, McpServer


async def list_all(db: AsyncSession) -> list[McpServer]:
    return list(await db.scalars(select(McpServer).order_by(McpServer.name)))


async def get(db: AsyncSession, server_id: uuid.UUID) -> McpServer | None:
    return await db.get(McpServer, server_id)


async def get_by_name(db: AsyncSession, name: str) -> McpServer | None:
    return await db.scalar(select(McpServer).where(McpServer.name == name))


async def existing_ids(db: AsyncSession, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    return set(await db.scalars(select(McpServer.id).where(McpServer.id.in_(ids))))


async def create(db: AsyncSession, **values: Any) -> McpServer:
    server = McpServer(**values)
    db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


async def update_fields(db: AsyncSession, server: McpServer, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(server, key, value)
    server.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(server)


async def delete_server(db: AsyncSession, server: McpServer) -> None:
    await db.execute(delete(McpServer).where(McpServer.id == server.id))


async def sync_agent(db: AsyncSession, agent_id: uuid.UUID, server_ids: set[uuid.UUID]) -> None:
    await db.execute(delete(AgentMcpServer).where(AgentMcpServer.agent_id == agent_id))
    if server_ids:
        await db.execute(
            insert(AgentMcpServer),
            [{"agent_id": agent_id, "mcp_server_id": s} for s in server_ids],
        )


async def get_for_agents(
    db: AsyncSession, agent_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[McpServer]]:
    result: dict[uuid.UUID, list[McpServer]] = defaultdict(list)
    if not agent_ids:
        return result
    rows = await db.execute(
        select(AgentMcpServer.agent_id, McpServer)
        .join(McpServer, McpServer.id == AgentMcpServer.mcp_server_id)
        .where(AgentMcpServer.agent_id.in_(agent_ids))
        .order_by(McpServer.name)
    )
    for agent_id, server in rows:
        result[agent_id].append(server)
    return result
