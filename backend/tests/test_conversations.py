from tests.conftest import auth


async def _agent(client, user, **body):
    resp = await client.post("/api/agents", json={"name": "Agent", **body}, headers=auth(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _conversation(client, user, agent_id, **body):
    resp = await client.post(
        "/api/conversations", json={"agentId": agent_id, **body}, headers=auth(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_conversation_for_visible_agent(client, make_user):
    user = await make_user()
    agent = await _agent(client, user, icon="🤖")
    conversation = await _conversation(client, user, agent["id"])
    assert conversation["title"] == "New conversation"
    assert conversation["agent"] == {"id": agent["id"], "name": "Agent", "icon": "🤖"}


async def test_cannot_run_invisible_or_gateway_agents(client, make_user):
    owner = await make_user()
    other = await make_user()
    private = await _agent(client, owner)
    resp = await client.post(
        "/api/conversations", json={"agentId": private["id"]}, headers=auth(other)
    )
    assert resp.status_code == 404

    gateway = await _agent(client, owner, agentType="mcp_gateway")
    resp = await client.post(
        "/api/conversations", json={"agentId": gateway["id"]}, headers=auth(owner)
    )
    assert resp.status_code == 400


async def test_org_agent_can_be_run_by_members(client, make_user):
    admin = await make_user(role="admin")
    member = await make_user()
    agent = await _agent(client, admin, scope="org")
    await _conversation(client, member, agent["id"])


async def test_conversations_are_private(client, make_user):
    admin = await make_user(role="admin")
    member = await make_user()
    agent = await _agent(client, admin, scope="org")
    conversation = await _conversation(client, member, agent["id"])

    # Not even admins see other users' conversations.
    resp = await client.get(f"/api/conversations/{conversation['id']}", headers=auth(admin))
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "hi"},
        headers=auth(admin),
    )
    assert resp.status_code == 404
    listed = (await client.get("/api/conversations", headers=auth(admin))).json()
    assert listed["data"] == []


async def test_send_message_queues_a_run_and_titles_the_conversation(client, make_user):
    user = await make_user()
    agent = await _agent(client, user)
    conversation = await _conversation(client, user, agent["id"])

    resp = await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "Summarize   the quarterly report"},
        headers=auth(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["message"]["role"] == "user"
    assert body["message"]["content"] == [
        {"type": "text", "text": "Summarize   the quarterly report"}
    ]
    assert body["run"]["status"] == "queued"
    assert body["run"]["trigger"] == "chat"

    detail = (
        await client.get(f"/api/conversations/{conversation['id']}", headers=auth(user))
    ).json()
    assert detail["title"] == "Summarize the quarterly report"
    assert detail["activeRun"]["id"] == body["run"]["id"]
    assert len(detail["messages"]) == 1


async def test_second_message_while_running_is_rejected(client, make_user):
    user = await make_user()
    agent = await _agent(client, user)
    conversation = await _conversation(client, user, agent["id"])
    url = f"/api/conversations/{conversation['id']}/messages"
    assert (await client.post(url, json={"content": "a"}, headers=auth(user))).status_code == 201
    resp = await client.post(url, json={"content": "b"}, headers=auth(user))
    assert resp.status_code == 409


async def test_deleted_agent_blocks_new_messages(client, make_user):
    user = await make_user()
    agent = await _agent(client, user)
    conversation = await _conversation(client, user, agent["id"])
    await client.delete(f"/api/agents/{agent['id']}", headers=auth(user))
    resp = await client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "hi"},
        headers=auth(user),
    )
    assert resp.status_code == 404
    # The history is still readable.
    resp = await client.get(f"/api/conversations/{conversation['id']}", headers=auth(user))
    assert resp.status_code == 200


async def test_rename_and_delete_conversation(client, make_user):
    user = await make_user()
    agent = await _agent(client, user)
    conversation = await _conversation(client, user, agent["id"], title="Old")
    url = f"/api/conversations/{conversation['id']}"
    resp = await client.patch(url, json={"title": "New"}, headers=auth(user))
    assert resp.json()["title"] == "New"
    assert (await client.delete(url, headers=auth(user))).status_code == 200
    assert (await client.get(url, headers=auth(user))).status_code == 404


async def test_cannot_delete_conversation_with_active_run(client, make_user):
    user = await make_user()
    agent = await _agent(client, user)
    conversation = await _conversation(client, user, agent["id"])
    url = f"/api/conversations/{conversation['id']}"
    await client.post(f"{url}/messages", json={"content": "hi"}, headers=auth(user))
    assert (await client.delete(url, headers=auth(user))).status_code == 409
