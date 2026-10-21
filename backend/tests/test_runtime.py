"""The worker and agent loop, driven by a scripted model (no real API calls)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Run
from app.services.runtime import executor as executor_module
from app.services.runtime.tools import ServerToolbox, ToolOutput
from app.worker import Worker, reap_stale_runs
from tests.conftest import auth
from tests.fakes import FakeLLM, RecordingToolbox, block_forever, text_turn, tool_turn, turn


async def _chat(client, user, content="Hello", **agent_body):
    agent = await client.post(
        "/api/agents", json={"name": "Agent", **agent_body}, headers=auth(user)
    )
    conversation = await client.post(
        "/api/conversations", json={"agentId": agent.json()["id"]}, headers=auth(user)
    )
    conversation_id = conversation.json()["id"]
    resp = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=auth(user),
    )
    assert resp.status_code == 201, resp.text
    return conversation_id, resp.json()["run"]["id"]


def _worker(llm, toolbox=None):
    return Worker(
        llm=llm,
        toolbox_factory=lambda agent, _c: toolbox or ServerToolbox(agent),
        concurrency=4,
    )


async def _run_all(llm, toolbox=None):
    worker = _worker(llm, toolbox)
    await worker.claim_available()
    await worker.wait_idle()


async def _get(client, user, path):
    resp = await client.get(path, headers=auth(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _events(client, user, run_id, after=None):
    path = f"/api/runs/{run_id}/events" + (f"?after={after}" if after is not None else "")
    resp = await client.get(path, headers=auth(user))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = []
    for chunk in resp.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
        events.append((fields.get("id"), fields["event"], json.loads(fields["data"])))
    return events


async def test_simple_answer(client, make_user):
    user = await make_user()
    conversation_id, run_id = await _chat(client, user, systemPrompt="Be brief", effort="high")
    llm = FakeLLM(text_turn("Hi there"))
    await _run_all(llm)

    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "succeeded"
    assert run["output"] == "Hi there"
    assert run["inputTokens"] == 10
    assert run["outputTokens"] == 5
    assert run["model"] == "claude-opus-5-5"

    request = llm.requests[0]
    assert request.system == "Be brief"
    assert request.effort == "high"
    assert request.messages == [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]

    detail = await _get(client, user, f"/api/conversations/{conversation_id}")
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["runId"] == run_id
    assert detail["activeRun"] is None


async def test_assistant_content_is_replayed_unchanged(client, make_user):
    user = await make_user()
    conversation_id, _ = await _chat(client, user)
    content = [
        {"type": "thinking", "thinking": "summary", "signature": "sig=="},
        {"type": "text", "text": "First"},
    ]
    await _run_all(FakeLLM(turn(content)))

    await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Again"},
        headers=auth(user),
    )
    llm = FakeLLM(text_turn("Second"))
    await _run_all(llm)
    assert llm.requests[0].messages[1] == {"role": "assistant", "content": content}


async def test_tool_loop(client, make_user):
    user = await make_user()
    conversation_id, run_id = await _chat(client, user)
    toolbox = RecordingToolbox({"echo": ToolOutput("echoed")})
    llm = FakeLLM(
        tool_turn(("t1", "echo", {"x": 1}), ("t2", "echo", {"x": 2}), text="Let me check"),
        text_turn("Done"),
    )
    await _run_all(llm, toolbox)

    assert toolbox.calls == [("echo", {"x": 1}), ("echo", {"x": 2})]
    assert llm.requests[0].tools == toolbox.definitions()
    # Both results come back in one user message.
    second = llm.requests[1].messages
    assert second[-1] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "echoed", "is_error": False},
            {"type": "tool_result", "tool_use_id": "t2", "content": "echoed", "is_error": False},
        ],
    }
    detail = await _get(client, user, f"/api/conversations/{conversation_id}")
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "succeeded"
    assert run["inputTokens"] == 20

    types = [e[1] for e in await _events(client, user, run_id)]
    assert types[0] == "run_started"
    assert types.count("tool_call") == 2 and types.count("tool_result") == 2
    assert types[-2:] == ["run_finished", "done"]


async def test_pause_turn_is_resumed_without_a_new_user_message(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)
    paused = [{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}}]
    llm = FakeLLM(turn(paused, stop_reason="pause_turn"), text_turn("Found it"))
    await _run_all(llm)
    assert llm.requests[1].messages[-1] == {"role": "assistant", "content": paused}
    assert (await _get(client, user, f"/api/runs/{run_id}"))["status"] == "succeeded"


async def test_turn_limit(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user, maxTurns=2)
    llm = FakeLLM(tool_turn(("t1", "echo", {})), tool_turn(("t2", "echo", {})))
    await _run_all(llm, RecordingToolbox())
    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "failed"
    assert "2 turns" in run["error"]


async def test_refusal_fails_without_storing_partial_output(client, make_user):
    user = await make_user()
    conversation_id, run_id = await _chat(client, user)
    refusal = turn(
        [{"type": "text", "text": "partial"}],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber"},
    )
    await _run_all(FakeLLM(refusal))
    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "failed"
    assert "cyber" in run["error"]
    detail = await _get(client, user, f"/api/conversations/{conversation_id}")
    assert [m["role"] for m in detail["messages"]] == ["user"]
    assert "turn_reset" in [e[1] for e in await _events(client, user, run_id)]


async def test_truncated_tool_call_is_not_executed(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)
    truncated = turn(
        [{"type": "tool_use", "id": "t1", "name": "echo", "input": {}}], stop_reason="max_tokens"
    )
    toolbox = RecordingToolbox()
    await _run_all(FakeLLM(truncated), toolbox)
    assert toolbox.calls == []
    assert (await _get(client, user, f"/api/runs/{run_id}"))["status"] == "failed"


async def test_model_error_fails_the_run(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)

    async def boom():
        raise RuntimeError("upstream exploded")

    await _run_all(FakeLLM(boom))
    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "failed"
    assert run["error"] == "upstream exploded"


async def test_cancel_running_run_closes_dangling_tool_calls(client, make_user, monkeypatch):
    monkeypatch.setattr(executor_module, "HEARTBEAT_SECONDS", 0.05)
    user = await make_user()
    conversation_id, run_id = await _chat(client, user)

    tool_started = asyncio.Event()

    class SlowToolbox(RecordingToolbox):
        async def execute(self, name, tool_input):
            tool_started.set()
            await asyncio.Event().wait()

    worker = _worker(FakeLLM(tool_turn(("t1", "echo", {}))), SlowToolbox())
    await worker.claim_available()
    await asyncio.wait_for(tool_started.wait(), 5)

    resp = await client.post(f"/api/runs/{run_id}/cancel", headers=auth(user))
    assert resp.status_code == 200
    await asyncio.wait_for(worker.wait_idle(), 5)

    assert (await _get(client, user, f"/api/runs/{run_id}"))["status"] == "cancelled"
    messages = (await _get(client, user, f"/api/conversations/{conversation_id}"))["messages"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"][0]["tool_use_id"] == "t1"
    assert messages[-1]["content"][0]["is_error"] is True

    # The conversation can continue.
    resp = await client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "next"},
        headers=auth(user),
    )
    assert resp.status_code == 201


async def test_cancel_queued_run(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)
    resp = await client.post(f"/api/runs/{run_id}/cancel", headers=auth(user))
    assert resp.json()["status"] == "cancelled"
    # No worker picks it up.
    assert await _worker(FakeLLM()).claim_available() == []
    assert [e[1] for e in await _events(client, user, run_id)] == ["run_finished", "done"]
    resp = await client.post(f"/api/runs/{run_id}/cancel", headers=auth(user))
    assert resp.status_code == 409


async def test_worker_shutdown_fails_running_runs(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)
    worker = _worker(FakeLLM(block_forever))
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if (await _get(client, user, f"/api/runs/{run_id}"))["status"] == "running":
            break
    stop.set()
    await asyncio.wait_for(task, 5)
    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "failed"
    assert "worker stopped" in run["error"]


async def test_reaper_fails_runs_with_stale_heartbeat(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)
    async with SessionLocal() as db:
        await db.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status="running", heartbeat_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await db.commit()
    assert [str(r) for r in await reap_stale_runs()] == [run_id]
    run = await _get(client, user, f"/api/runs/{run_id}")
    assert run["status"] == "failed"
    assert "stopped responding" in run["error"]


async def test_events_resume_after_seq(client, make_user):
    user = await make_user()
    _, run_id = await _chat(client, user)
    await _run_all(FakeLLM(text_turn("Hello world")))
    events = await _events(client, user, run_id)
    assert ("text_delta", {"text": "Hello world"}) in [(e[1], e[2]) for e in events]
    seqs = [int(e[0]) for e in events if e[0] is not None]
    assert seqs == sorted(seqs)

    resumed = await _events(client, user, run_id, after=seqs[-2])
    assert [e[1] for e in resumed] == ["run_finished", "done"]

    resp = await client.get(
        f"/api/runs/{run_id}/events", headers={**auth(user), "Last-Event-ID": str(seqs[-1])}
    )
    assert "event: done" in resp.text and "run_finished" not in resp.text


async def test_runs_are_private(client, make_user):
    user = await make_user()
    other = await make_user(role="admin")
    _, run_id = await _chat(client, user)
    for path in (f"/api/runs/{run_id}", f"/api/runs/{run_id}/events"):
        assert (await client.get(path, headers=auth(other))).status_code == 404
    resp = await client.post(f"/api/runs/{run_id}/cancel", headers=auth(other))
    assert resp.status_code == 404


async def test_async_run_api(client, make_user):
    user = await make_user()
    agent = (await client.post("/api/agents", json={"name": "Batch"}, headers=auth(user))).json()
    resp = await client.post(
        f"/api/agents/{agent['id']}/runs", json={"input": "Do the thing"}, headers=auth(user)
    )
    assert resp.status_code == 202, resp.text
    run = resp.json()
    assert run["trigger"] == "api"
    assert run["status"] == "queued"

    await _run_all(FakeLLM(text_turn("Thing done")))
    detail = await _get(client, user, f"/api/runs/{run['id']}")
    assert detail["output"] == "Thing done"

    listed = await _get(client, user, "/api/runs?trigger=api&status=succeeded")
    assert [r["id"] for r in listed["data"]] == [run["id"]]
    assert listed["data"][0]["agent"]["name"] == "Batch"
    conversation = await _get(client, user, f"/api/conversations/{run['conversationId']}")
    assert conversation["title"] == "Do the thing"


async def test_runs_respect_concurrency_limit(client, make_user):
    user = await make_user()
    for _ in range(3):
        await _chat(client, user)
    worker = Worker(
        llm=FakeLLM(block_forever, block_forever, block_forever),
        toolbox_factory=lambda agent, _c: ServerToolbox(agent),
        concurrency=2,
    )
    assert len(await worker.claim_available()) == 2
    assert await worker.claim_available() == []
    # Clean up the blocked runs.
    await worker._shutdown()
