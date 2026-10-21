"""Per-conversation sandbox containers for the bash and file editor tools.

Each conversation gets one container (`agent-sandbox-<conversation id>`) and one volume
(`agent-ws-<conversation id>`) mounted at /workspace, so files survive between runs and
container restarts. Containers run as an unprivileged user with every capability dropped,
a read-only root filesystem, resource limits and, by default, no network.

The worker talks to the Docker daemon, which effectively grants it root on the host.
That is acceptable for development; production deployments should set
`AGENT_MANAGER_SANDBOX_RUNTIME=runsc` (gVisor) or run sandboxes on a separate host.
"""

import asyncio
import contextlib
import io
import logging
import posixpath
import tarfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import docker
import docker.errors
from docker.models.containers import Container

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

WORKSPACE = "/workspace"
SANDBOX_USER = "1000:1000"
_LABEL = "agent-manager.sandbox"
_CONVERSATION_LABEL = "agent-manager.conversation"
_NETWORK_LABEL = "agent-manager.network"
# coreutils `timeout` exits with 124 when the time limit is hit.
_TIMEOUT_EXIT_CODE = 124


class SandboxError(Exception):
    """The sandbox could not be created or reached (as opposed to a failing command)."""


@dataclass
class ExecResult:
    exit_code: int
    output: str
    timed_out: bool = False


class Sandbox(Protocol):
    async def exec(self, argv: list[str], *, timeout: int) -> ExecResult:
        """Run a command as the sandbox user in /workspace; stdout and stderr combined."""
        ...

    async def read_file(self, path: str) -> bytes: ...

    async def write_file(self, path: str, content: bytes) -> None: ...


class SandboxProvider(Protocol):
    async def get(self, conversation_id: uuid.UUID, *, network: bool) -> Sandbox:
        """Return the conversation's running sandbox, creating or starting it as needed."""
        ...


def in_workspace(path: str) -> str | None:
    """Normalize an absolute path and return it if it stays inside /workspace.

    The check is lexical: a symlink can still point elsewhere, but only within the
    container, whose filesystem holds nothing outside the workspace worth protecting.
    """
    if not path.startswith("/"):
        return None
    normalized = posixpath.normpath(path)
    if normalized == WORKSPACE or normalized.startswith(WORKSPACE + "/"):
        return normalized
    return None


# =============================================================================
# Docker implementation
# =============================================================================


class DockerSandbox:
    def __init__(self, container: Container, on_use: Callable[[], None]):
        self._container = container
        self._on_use = on_use

    @property
    def container_id(self) -> str:
        return self._container.id or ""

    async def exec(self, argv: list[str], *, timeout: int) -> ExecResult:
        self._on_use()
        cmd = ["timeout", "--kill-after=5", str(timeout), *argv]
        try:
            exit_code, output = await asyncio.to_thread(
                self._container.exec_run, cmd, user=SANDBOX_USER, workdir=WORKSPACE
            )
        except docker.errors.DockerException as exc:
            raise SandboxError(f"Could not run the command: {exc}") from exc
        return ExecResult(
            exit_code=exit_code,
            output=(output or b"").decode("utf-8", errors="replace"),
            timed_out=exit_code == _TIMEOUT_EXIT_CODE,
        )

    async def read_file(self, path: str) -> bytes:
        self._on_use()
        try:
            stream, _ = await asyncio.to_thread(self._container.get_archive, path)
            data = b"".join(await asyncio.to_thread(list, stream))
        except docker.errors.NotFound as exc:
            raise FileNotFoundError(path) from exc
        except docker.errors.DockerException as exc:
            raise SandboxError(f"Could not read {path}: {exc}") from exc
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.next()
            if member is None or not member.isfile():
                raise IsADirectoryError(path)
            extracted = archive.extractfile(member)
            assert extracted is not None
            return extracted.read()

    async def write_file(self, path: str, content: bytes) -> None:
        self._on_use()
        directory, name = posixpath.split(path)
        result = await self.exec(["mkdir", "-p", "--", directory], timeout=30)
        if result.exit_code != 0:
            raise SandboxError(result.output.strip() or f"Could not create {directory}")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            info.uid = info.gid = 1000
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(content))
        try:
            ok = await asyncio.to_thread(self._container.put_archive, directory, buffer.getvalue())
        except docker.errors.DockerException as exc:
            raise SandboxError(f"Could not write {path}: {exc}") from exc
        if not ok:
            raise SandboxError(f"Could not write {path}")


class DockerSandboxProvider:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client: docker.DockerClient | None = None
        # container name -> monotonic time of last use; drives the idle reaper
        self._last_used: dict[str, float] = {}

    async def get(self, conversation_id: uuid.UUID, *, network: bool) -> DockerSandbox:
        name = container_name(conversation_id)
        try:
            container = await asyncio.to_thread(self._ensure_running, conversation_id, network)
        except docker.errors.DockerException as exc:
            raise SandboxError(f"The sandbox is unavailable: {exc}") from exc
        self._touch(name)
        return DockerSandbox(container, on_use=lambda: self._touch(name))

    async def remove(self, conversation_id: uuid.UUID) -> None:
        """Remove the container and its workspace volume."""
        await asyncio.to_thread(self._remove, conversation_id)

    async def reap(
        self, existing_conversations: Callable[[set[uuid.UUID]], Awaitable[set[uuid.UUID]]]
    ) -> None:
        """Stop idle sandboxes and remove those whose conversation was deleted."""
        containers = await asyncio.to_thread(self._list)
        by_conversation: dict[uuid.UUID, Container] = {}
        for container in containers:
            try:
                by_conversation[uuid.UUID(container.labels[_CONVERSATION_LABEL])] = container
            except (KeyError, ValueError):
                continue
        alive = await existing_conversations(set(by_conversation))
        idle_after = self._settings.sandbox_idle_minutes * 60
        now = time.monotonic()
        for conversation_id, container in by_conversation.items():
            name = container.name or ""
            if conversation_id not in alive:
                logger.info("Removing sandbox of deleted conversation %s", conversation_id)
                await self.remove(conversation_id)
                self._last_used.pop(name, None)
            elif container.status == "running":
                # Containers started before this worker (re)started get a full idle period.
                last = self._last_used.setdefault(name, now)
                if now - last > idle_after:
                    logger.info("Stopping idle sandbox %s", name)
                    await asyncio.to_thread(container.stop, timeout=5)
                    self._last_used.pop(name, None)

    # -------------------------------------------------------------------------
    # Blocking helpers (run in a thread)
    # -------------------------------------------------------------------------

    @property
    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def _ensure_running(self, conversation_id: uuid.UUID, network: bool) -> Container:
        name = container_name(conversation_id)
        wanted_network = "on" if network else "off"
        try:
            container = self._docker.containers.get(name)
        except docker.errors.NotFound:
            container = None
        if container is not None and container.labels.get(_NETWORK_LABEL) != wanted_network:
            # The agent's network setting changed; recreate (the workspace volume is kept).
            container.remove(force=True)
            container = None
        if container is None:
            try:
                container = self._create(conversation_id, network)
            except docker.errors.APIError as exc:
                if exc.status_code != 409:
                    raise
                # Created concurrently by someone else.
                container = self._docker.containers.get(name)
        if container.status != "running":
            container.start()
            container.reload()
        return container

    def _create(self, conversation_id: uuid.UUID, network: bool) -> Container:
        settings = self._settings
        options: dict[str, Any] = {}
        if settings.sandbox_runtime:
            options["runtime"] = settings.sandbox_runtime
        return self._docker.containers.run(
            settings.sandbox_image,
            name=container_name(conversation_id),
            detach=True,
            init=True,
            user=SANDBOX_USER,
            working_dir=WORKSPACE,
            labels={
                _LABEL: "1",
                _CONVERSATION_LABEL: str(conversation_id),
                _NETWORK_LABEL: "on" if network else "off",
            },
            network_mode="bridge" if network else "none",
            mem_limit=settings.sandbox_memory,
            memswap_limit=settings.sandbox_memory,
            nano_cpus=int(settings.sandbox_cpus * 1e9),
            pids_limit=settings.sandbox_pids_limit,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            read_only=True,
            tmpfs={"/tmp": "rw,size=512m", "/home/agent": "rw,size=512m,uid=1000,gid=1000"},
            volumes={volume_name(conversation_id): {"bind": WORKSPACE, "mode": "rw"}},
            **options,
        )

    def _remove(self, conversation_id: uuid.UUID) -> None:
        with contextlib.suppress(docker.errors.NotFound):
            self._docker.containers.get(container_name(conversation_id)).remove(force=True)
        with contextlib.suppress(docker.errors.NotFound):
            self._docker.volumes.get(volume_name(conversation_id)).remove(force=True)

    def _list(self) -> list[Container]:
        return self._docker.containers.list(all=True, filters={"label": f"{_LABEL}=1"})

    def _touch(self, name: str) -> None:
        self._last_used[name] = time.monotonic()


def container_name(conversation_id: uuid.UUID) -> str:
    return f"agent-sandbox-{conversation_id}"


def volume_name(conversation_id: uuid.UUID) -> str:
    return f"agent-ws-{conversation_id}"
