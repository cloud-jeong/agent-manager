"""Visibility and modification rules per scope (ported from Archestra's access model)."""

from tests.conftest import TEST_PASSWORD, auth


async def _create(client, user, **body):
    resp = await client.post("/api/agents", json={"name": "Agent", **body}, headers=auth(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _list_ids(client, user, **params):
    resp = await client.get("/api/agents", params=params, headers=auth(user))
    assert resp.status_code == 200, resp.text
    return {a["id"] for a in resp.json()["data"]}


async def test_requires_authentication(client):
    resp = await client.get("/api/agents")
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "api_authentication_error"


async def test_login_returns_working_token(client, make_user):
    user = await make_user()
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    token = resp.json()["accessToken"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == user.email

    bad = await client.post("/api/auth/login", json={"email": user.email, "password": "wrong"})
    assert bad.status_code == 401


async def test_personal_agent_visible_only_to_author_shared_users_and_admin(client, make_user):
    author, shared, stranger, admin = (
        await make_user(),
        await make_user(),
        await make_user(),
        await make_user(role="admin"),
    )
    agent = await _create(client, author, users=[{"userId": str(shared.id)}])

    assert agent["id"] in await _list_ids(client, author)
    assert agent["id"] in await _list_ids(client, shared)
    assert agent["id"] in await _list_ids(client, admin)
    assert agent["id"] not in await _list_ids(client, stranger)

    resp = await client.get(f"/api/agents/{agent['id']}", headers=auth(stranger))
    assert resp.status_code == 404


async def test_team_agent_visible_to_team_members_only(client, make_user, make_team):
    team_admin, member, outsider = await make_user(), await make_user(), await make_user()
    team = await make_team(members={team_admin.id: "team_admin", member.id: "member"})
    agent = await _create(client, team_admin, scope="team", teams=[str(team.id)])

    assert agent["id"] in await _list_ids(client, member)
    assert agent["id"] not in await _list_ids(client, outsider)


async def test_org_agent_visible_to_everyone_but_only_admin_creates_it(client, make_user):
    admin, member = await make_user(role="admin"), await make_user()

    resp = await client.post(
        "/api/agents", json={"name": "Org", "scope": "org"}, headers=auth(member)
    )
    assert resp.status_code == 403

    agent = await _create(client, admin, scope="org")
    assert agent["id"] in await _list_ids(client, member)
    assert agent["canModify"] is True


async def test_member_cannot_modify_org_agent_and_gets_404(client, make_user):
    admin, member = await make_user(role="admin"), await make_user()
    agent = await _create(client, admin, scope="org")

    listed = (await client.get(f"/api/agents/{agent['id']}", headers=auth(member))).json()
    assert listed["canModify"] is False

    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"name": "Hijacked"}, headers=auth(member)
    )
    assert resp.status_code == 404
    resp = await client.delete(f"/api/agents/{agent['id']}", headers=auth(member))
    assert resp.status_code == 404


async def test_team_scope_requires_team_admin_of_every_assigned_team(client, make_user, make_team):
    user = await make_user()
    administered = await make_team(members={user.id: "team_admin"})
    member_only = await make_team(members={user.id: "member"})
    foreign = await make_team()

    for team in (member_only, foreign):
        resp = await client.post(
            "/api/agents",
            json={"name": "T", "scope": "team", "teams": [str(team.id)]},
            headers=auth(user),
        )
        assert resp.status_code == 403, team.name

    await _create(client, user, scope="team", teams=[str(administered.id)])


async def test_plain_team_member_cannot_modify_team_agent(client, make_user, make_team):
    team_admin, member = await make_user(), await make_user()
    team = await make_team(members={team_admin.id: "team_admin", member.id: "member"})
    agent = await _create(client, team_admin, scope="team", teams=[str(team.id)])

    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"name": "Renamed"}, headers=auth(member)
    )
    assert resp.status_code == 404


async def test_team_admin_edit_keeps_teams_they_do_not_control(client, make_user, make_team):
    admin, team_admin = await make_user(role="admin"), await make_user()
    mine = await make_team(members={team_admin.id: "team_admin"})
    other = await make_team()
    agent = await _create(client, admin, scope="team", teams=[str(mine.id), str(other.id)])

    # Removing a team the caller does not administer is rejected...
    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"teams": [str(mine.id)]}, headers=auth(team_admin)
    )
    assert resp.status_code == 403

    # ...but other edits leave it in place.
    resp = await client.put(
        f"/api/agents/{agent['id']}", json={"name": "Renamed"}, headers=auth(team_admin)
    )
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()["teams"]} == {str(mine.id), str(other.id)}


async def test_write_share_allows_editing_personal_agent(client, make_user):
    author, writer, reader = await make_user(), await make_user(), await make_user()
    agent = await _create(
        client,
        author,
        users=[
            {"userId": str(writer.id), "level": "write"},
            {"userId": str(reader.id), "level": "use"},
        ],
    )

    ok = await client.put(
        f"/api/agents/{agent['id']}", json={"description": "x"}, headers=auth(writer)
    )
    assert ok.status_code == 200
    denied = await client.put(
        f"/api/agents/{agent['id']}", json={"description": "y"}, headers=auth(reader)
    )
    assert denied.status_code == 404
