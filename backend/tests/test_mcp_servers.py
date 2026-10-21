from sqlalchemy import select

from app.db import SessionLocal
from app.models import McpServer
from app.services.runtime.tools import AgentToolbox
from app.worker import Worker
from tests.conftest import auth
from tests.fakes import FakeLLM, FakeSandboxProvider, text_turn

SERVER = {"name": "github", "url": "https://mcp.example.com/mcp", "token": "secret-token"}


async def _create_server(client, admin, **overrides):
    resp = await client.post("/api/mcp-servers", json={**SERVER, **overrides}, headers=auth(admin))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_admin_manages_servers_and_token_is_write_only(client, make_user):
    admin = await make_user(role="admin")
    member = await make_user()
    server = await _create_server(client, admin)
    assert server["hasToken"] is True
    assert "token" not in server

    # Stored encrypted.
    async with SessionLocal() as db:
        row = await db.scalar(select(McpServer))
        assert row.token_encrypted and "secret-token" not in row.token_encrypted

    listed = (await client.get("/api/mcp-servers", headers=auth(member))).json()
    assert [s["name"] for s in listed] == ["github"]
    assert "token" not in listed[0]

    url = f"/api/mcp-servers/{server['id']}"
    resp = await client.put(url, json={"description": "Code"}, headers=auth(admin))
    assert resp.json()["hasToken"] is True  # omitted token is kept
    resp = await client.put(url, json={"token": None}, headers=auth(admin))
    assert resp.json()["hasToken"] is False


async def test_members_cannot_manage_servers(client, make_user):
    admin = await make_user(role="admin")
    member = await make_user()
    resp = await client.post("/api/mcp-servers", json=SERVER, headers=auth(member))
    assert resp.status_code == 403
    server = await _create_server(client, admin)
    resp = await client.delete(f"/api/mcp-servers/{server['id']}", headers=auth(member))
    assert resp.status_code == 403


async def test_server_validation(client, make_user):
    admin = await make_user(role="admin")
    await _create_server(client, admin)
    cases = [
        ({"name": "github"}, 409),
        ({"name": "has space"}, 400),
        ({"name": "plain", "url": "http://mcp.example.com"}, 400),
        ({"name": "bad", "url": "not a url"}, 400),
    ]
    for overrides, expected in cases:
        resp = await client.post(
            "/api/mcp-servers", json={**SERVER, **overrides}, headers=auth(admin)
        )
        assert resp.status_code == expected, overrides


async def test_agent_mcp_servers_are_sent_to_the_model(client, make_user):
    admin = await make_user(role="admin")
    server = await _create_server(client, admin)
    plain = await _create_server(
        client, admin, name="docs", url="https://docs.example.com/mcp", token=None
    )

    resp = await client.post(
        "/api/agents",
        json={"name": "A", "mcpServers": [server["id"], plain["id"]]},
        headers=auth(admin),
    )
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    assert [m["name"] for m in agent["mcpServers"]] == ["docs", "github"]

    resp = await client.post(
        f"/api/agents/{agent['id']}/runs", json={"input": "hi"}, headers=auth(admin)
    )
    llm = FakeLLM(text_turn("ok"))
    worker = Worker(
        llm=llm,
        toolbox_factory=lambda a, c: AgentToolbox(a, c.id, FakeSandboxProvider()),
        concurrency=1,
    )
    await worker.claim_available()
    await worker.wait_idle()

    request = llm.requests[0]
    assert request.mcp_servers == [
        {"type": "url", "url": "https://docs.example.com/mcp", "name": "docs"},
        {
            "type": "url",
            "url": "https://mcp.example.com/mcp",
            "name": "github",
            "authorization_token": "secret-token",
        },
    ]
    assert request.tools == [
        {"type": "mcp_toolset", "mcp_server_name": "docs"},
        {"type": "mcp_toolset", "mcp_server_name": "github"},
    ]
    assert request.betas == ["mcp-client-2025-11-20"]


async def test_unknown_server_and_deleting_detaches(client, make_user):
    admin = await make_user(role="admin")
    resp = await client.post(
        "/api/agents",
        json={"name": "A", "mcpServers": ["00000000-0000-0000-0000-000000000000"]},
        headers=auth(admin),
    )
    assert resp.status_code == 400

    server = await _create_server(client, admin)
    agent = (
        await client.post(
            "/api/agents", json={"name": "A", "mcpServers": [server["id"]]}, headers=auth(admin)
        )
    ).json()
    await client.delete(f"/api/mcp-servers/{server['id']}", headers=auth(admin))
    fetched = (await client.get(f"/api/agents/{agent['id']}", headers=auth(admin))).json()
    assert fetched["mcpServers"] == []
