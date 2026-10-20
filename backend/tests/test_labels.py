from tests.conftest import auth


async def _create(client, user, name, labels):
    resp = await client.post(
        "/api/agents", json={"name": name, "labels": labels}, headers=auth(user)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _names(client, user, labels):
    resp = await client.get("/api/agents", params={"labels": labels}, headers=auth(user))
    assert resp.status_code == 200, resp.text
    return {a["name"] for a in resp.json()["data"]}


async def test_labels_are_returned_sorted_by_key(client, make_user):
    user = await make_user()
    agent = await _create(
        client, user, "A", [{"key": "team", "value": "x"}, {"key": "env", "value": "prod"}]
    )
    assert agent["labels"] == [{"key": "env", "value": "prod"}, {"key": "team", "value": "x"}]


async def test_duplicate_label_keys_are_rejected(client, make_user):
    user = await make_user()
    resp = await client.post(
        "/api/agents",
        json={"name": "A", "labels": [{"key": "env", "value": "a"}, {"key": "env", "value": "b"}]},
        headers=auth(user),
    )
    assert resp.status_code == 400


async def test_label_filter_is_and_across_keys_or_within_values(client, make_user):
    user = await make_user()
    await _create(
        client, user, "prod-a", [{"key": "env", "value": "prod"}, {"key": "owner", "value": "a"}]
    )
    await _create(
        client, user, "dev-a", [{"key": "env", "value": "dev"}, {"key": "owner", "value": "a"}]
    )
    await _create(
        client, user, "prod-b", [{"key": "env", "value": "prod"}, {"key": "owner", "value": "b"}]
    )
    await _create(client, user, "none", [])

    assert await _names(client, user, "env:prod") == {"prod-a", "prod-b"}
    assert await _names(client, user, "env:prod|dev") == {"prod-a", "dev-a", "prod-b"}
    assert await _names(client, user, "env:prod|dev;owner:a") == {"prod-a", "dev-a"}

    bad = await client.get("/api/agents", params={"labels": "env"}, headers=auth(user))
    assert bad.status_code == 400


async def test_label_sync_replaces_labels_and_prunes_unused_keys(client, make_user):
    user = await make_user()
    agent = await _create(client, user, "A", [{"key": "env", "value": "prod"}])
    await _create(client, user, "B", [{"key": "owner", "value": "z"}])

    keys = (await client.get("/api/agents/labels/keys", headers=auth(user))).json()
    assert keys == ["env", "owner"]

    resp = await client.put(
        f"/api/agents/{agent['id']}",
        json={"labels": [{"key": "tier", "value": " gold "}]},
        headers=auth(user),
    )
    assert resp.json()["labels"] == [{"key": "tier", "value": "gold"}]

    keys = (await client.get("/api/agents/labels/keys", headers=auth(user))).json()
    assert keys == ["owner", "tier"]
    values = (
        await client.get("/api/agents/labels/values", params={"key": "tier"}, headers=auth(user))
    ).json()
    assert values == ["gold"]
