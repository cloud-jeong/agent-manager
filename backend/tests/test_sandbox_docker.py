"""DockerSandboxProvider against a real Docker daemon.

Skipped unless Docker is reachable and the sandbox image exists (`make sandbox-image`).
"""

import uuid

import docker
import docker.errors
import pytest

from app.config import get_settings
from app.services.runtime.sandbox import DockerSandboxProvider, container_name
from app.services.runtime.tools import run_bash, run_editor


def _docker_ready() -> bool:
    try:
        client = docker.from_env()
        client.images.get(get_settings().sandbox_image)
    except docker.errors.DockerException:
        return False
    return True


pytestmark = pytest.mark.skipif(not _docker_ready(), reason="Docker or sandbox image unavailable")


@pytest.fixture
async def sandbox_ids():
    provider = DockerSandboxProvider()
    ids: list[uuid.UUID] = []
    yield provider, ids
    for conversation_id in ids:
        await provider.remove(conversation_id)


async def test_isolation_and_persistence(sandbox_ids):
    provider, ids = sandbox_ids
    conversation_id = uuid.uuid4()
    ids.append(conversation_id)
    sandbox = await provider.get(conversation_id, network=False)

    whoami = await run_bash(sandbox, {"command": "id -u && pwd"})
    assert whoami.content == "1000\n/workspace"

    # No network, read-only root filesystem.
    net = await run_bash(sandbox, {"command": "curl -sS -m 5 https://example.com"})
    assert "[exit code" in net.content
    ro = await run_bash(sandbox, {"command": "touch /usr/x"})
    assert "Read-only file system" in ro.content

    # cd persists across calls; files persist across container restarts.
    await run_bash(sandbox, {"command": "mkdir -p proj && cd proj"})
    assert (await run_bash(sandbox, {"command": "pwd"})).content == "/workspace/proj"
    created = await run_editor(
        sandbox, {"command": "create", "path": "/workspace/proj/a.txt", "file_text": "héllo\n"}
    )
    assert not created.is_error
    client = docker.from_env()
    client.containers.get(container_name(conversation_id)).stop(timeout=1)

    sandbox = await provider.get(conversation_id, network=False)
    assert (await run_bash(sandbox, {"command": "cat proj/a.txt"})).content == "héllo"
    view = await run_editor(sandbox, {"command": "view", "path": "/workspace/proj/a.txt"})
    assert view.content.startswith("     1\théllo")


async def test_command_timeout(sandbox_ids, monkeypatch):
    provider, ids = sandbox_ids
    monkeypatch.setattr(get_settings(), "sandbox_command_timeout_seconds", 1)
    conversation_id = uuid.uuid4()
    ids.append(conversation_id)
    sandbox = await provider.get(conversation_id, network=False)
    result = await run_bash(sandbox, {"command": "sleep 10"})
    assert result.is_error
    assert "timed out after 1s" in result.content


async def test_network_setting_change_recreates_container_but_keeps_files(sandbox_ids):
    provider, ids = sandbox_ids
    conversation_id = uuid.uuid4()
    ids.append(conversation_id)
    sandbox = await provider.get(conversation_id, network=False)
    await run_bash(sandbox, {"command": "echo kept > f.txt"})
    first = sandbox.container_id

    sandbox = await provider.get(conversation_id, network=True)
    assert sandbox.container_id != first
    assert (await run_bash(sandbox, {"command": "cat f.txt"})).content == "kept"


async def test_reap_removes_sandboxes_of_deleted_conversations(sandbox_ids):
    provider, ids = sandbox_ids
    kept, deleted = uuid.uuid4(), uuid.uuid4()
    ids.extend([kept, deleted])
    await provider.get(kept, network=False)
    await provider.get(deleted, network=False)

    async def existing(candidates):
        return {c for c in candidates if c == kept}

    await provider.reap(existing)
    client = docker.from_env()
    names = {c.name for c in client.containers.list(all=True)}
    assert container_name(kept) in names
    assert container_name(deleted) not in names
    with pytest.raises(docker.errors.NotFound):
        client.volumes.get(f"agent-ws-{deleted}")
