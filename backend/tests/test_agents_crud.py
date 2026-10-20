from tests.conftest import auth


async def _create(client, user, **body):
    resp = await client.post("/api/agents", json={"name": "Agent", **body}, headers=auth(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_and_read_agent(client, make_user):
    user = await make_user(name="Alice")
    agent = await _create(
        client,
        user,
        name="Helper",
        description="Helps",
        systemPrompt="Be nice",
        icon="🤖",
        considerContextUntrusted=True,
    )
    assert agent["scope"] == "personal"
    assert agent["agentType"] == "agent"
    assert agent["authorName"] == "Alice"
    assert agent["canModify"] is True

    fetched = (await client.get(f"/api/agents/{agent['id']}", headers=auth(user))).json()
    assert fetched["systemPrompt"] == "Be nice"
    assert fetched["considerContextUntrusted"] is True


async def test_team_scope_needs_at_least_one_team(client, make_user):
    admin = await make_user(role="admin")
    resp = await client.post(
        "/api/agents", json={"name": "T", "scope": "team", "teams": []}, headers=auth(admin)
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "api_validation_error"


async def test_teams_are_dropped_when_scope_is_not_team(client, make_user, make_team):
    admin = await make_user(role="admin")
    team = await make_team()
    agent = await _create(client, admin, scope="org", teams=[str(team.id)])
    assert agent["teams"] == []


async def test_shared_agent_cannot_become_personal(client, make_user):
    admin = await make_user(role="admin")
    agent = await _create(client, admin, scope="org")
    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"scope": "personal"}, headers=auth(admin)
    )
    assert resp.status_code == 400


async def test_member_cannot_escalate_personal_agent_to_org(client, make_user):
    member = await make_user()
    agent = await _create(client, member)
    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"scope": "org"}, headers=auth(member)
    )
    assert resp.status_code == 403


async def test_partial_update_keeps_omitted_fields_and_can_clear_nullable(client, make_user):
    user = await make_user()
    agent = await _create(client, user, description="desc", systemPrompt="prompt")

    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"description": None}, headers=auth(user)
    )
    body = resp.json()
    assert body["description"] is None
    assert body["systemPrompt"] == "prompt"
    assert body["name"] == "Agent"

    resp = await client.put(f"/api/agents/{agent['id']}", json={"name": None}, headers=auth(user))
    assert resp.status_code == 400


async def test_soft_delete_restore_and_purge(client, make_user):
    user = await make_user()
    agent = await _create(client, user, name="Temp")

    assert (
        await client.delete(f"/api/agents/{agent['id']}", headers=auth(user))
    ).status_code == 200

    active = (await client.get("/api/agents", headers=auth(user))).json()["data"]
    assert agent["id"] not in {a["id"] for a in active}
    deleted = (
        await client.get("/api/agents", params={"status": "deleted"}, headers=auth(user))
    ).json()["data"]
    assert [a["id"] for a in deleted] == [agent["id"]]
    assert deleted[0]["deletedAt"] is not None

    restored = await client.post(f"/api/agents/{agent['id']}/restore", headers=auth(user))
    assert restored.status_code == 200
    assert restored.json()["deletedAt"] is None

    # Purging requires a soft delete first.
    resp = await client.delete(f"/api/agents/{agent['id']}/permanent", headers=auth(user))
    assert resp.status_code == 400
    await client.delete(f"/api/agents/{agent['id']}", headers=auth(user))
    resp = await client.delete(f"/api/agents/{agent['id']}/permanent", headers=auth(user))
    assert resp.status_code == 200
    resp = await client.get(f"/api/agents/{agent['id']}", headers=auth(user))
    assert resp.status_code == 404


async def test_restore_conflicts_with_active_agent_of_same_name(client, make_user):
    user = await make_user()
    original = await _create(client, user, name="Dup")
    await client.delete(f"/api/agents/{original['id']}", headers=auth(user))
    await _create(client, user, name="Dup")

    resp = await client.post(f"/api/agents/{original['id']}/restore", headers=auth(user))
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "api_conflict_error"


async def test_other_users_deleted_agents_are_not_listed(client, make_user):
    author, other = await make_user(), await make_user()
    agent = await _create(client, author)
    await client.delete(f"/api/agents/{agent['id']}", headers=auth(author))

    deleted = (
        await client.get("/api/agents", params={"status": "deleted"}, headers=auth(other))
    ).json()["data"]
    assert deleted == []
    resp = await client.post(f"/api/agents/{agent['id']}/restore", headers=auth(other))
    assert resp.status_code == 404


async def test_deleting_agent_clears_default_agent_pin(client, make_user):
    user = await make_user()
    agent = await _create(client, user)

    resp = await client.put(
        "/api/members/default-agent", json={"defaultAgentId": agent["id"]}, headers=auth(user)
    )
    assert resp.json()["defaultAgentId"] == agent["id"]

    await client.delete(f"/api/agents/{agent['id']}", headers=auth(user))
    resp = await client.get("/api/members/default-agent", headers=auth(user))
    assert resp.json()["defaultAgentId"] is None


async def test_cannot_pin_invisible_agent_as_default(client, make_user):
    author, other = await make_user(), await make_user()
    agent = await _create(client, author)
    resp = await client.put(
        "/api/members/default-agent", json={"defaultAgentId": agent["id"]}, headers=auth(other)
    )
    assert resp.status_code == 404


async def test_list_pagination_search_and_sorting(client, make_user):
    user = await make_user()
    for name in ["Bravo", "alpha", "Charlie", "Alphabet"]:
        await _create(client, user, name=name)

    resp = await client.get(
        "/api/agents",
        params={"sortBy": "name", "sortDirection": "asc", "limit": 2},
        headers=auth(user),
    )
    body = resp.json()
    assert [a["name"] for a in body["data"]] == ["alpha", "Alphabet"]
    assert body["pagination"] == {"total": 4, "limit": 2, "offset": 0, "hasNext": True}

    page2 = (
        await client.get(
            "/api/agents",
            params={"sortBy": "name", "sortDirection": "asc", "limit": 2, "offset": 2},
            headers=auth(user),
        )
    ).json()
    assert [a["name"] for a in page2["data"]] == ["Bravo", "Charlie"]
    assert page2["pagination"]["hasNext"] is False

    search = (await client.get("/api/agents", params={"name": "ALPHA"}, headers=auth(user))).json()
    assert {a["name"] for a in search["data"]} == {"alpha", "Alphabet"}

    # LIKE wildcards in the search term are matched literally.
    wildcard = (await client.get("/api/agents", params={"name": "%"}, headers=auth(user))).json()
    assert wildcard["data"] == []


async def test_filter_by_team_and_scope(client, make_user, make_team):
    admin = await make_user(role="admin")
    team_a, team_b = await make_team(name="A"), await make_team(name="B")
    in_a = await _create(client, admin, scope="team", teams=[str(team_a.id)])
    await _create(client, admin, scope="team", teams=[str(team_b.id)])
    org = await _create(client, admin, scope="org")

    by_team = (
        await client.get("/api/agents", params={"teamIds": str(team_a.id)}, headers=auth(admin))
    ).json()["data"]
    assert [a["id"] for a in by_team] == [in_a["id"]]

    by_scope = (
        await client.get("/api/agents", params={"scope": "org"}, headers=auth(admin))
    ).json()["data"]
    assert [a["id"] for a in by_scope] == [org["id"]]

    bad = await client.get("/api/agents", params={"teamIds": "nope"}, headers=auth(admin))
    assert bad.status_code == 400
