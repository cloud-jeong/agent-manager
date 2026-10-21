"""Tools offered to the model for one run, and execution of client-side tool calls.

Server tools (web search/fetch) run on Anthropic and only need a definition. The bash and
file editor tools are Anthropic-defined client tools: the model knows their input schema,
and they run here, inside the conversation's sandbox container.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings
from app.models import Agent
from app.services.runtime.sandbox import (
    WORKSPACE,
    Sandbox,
    SandboxError,
    SandboxProvider,
    in_workspace,
)

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}
WEB_FETCH_TOOL = {"type": "web_fetch_20260209", "name": "web_fetch"}
BASH_TOOL = {"type": "bash_20250124", "name": "bash"}
EDITOR_TOOL = {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"}

# Tool output beyond this is cut from the middle (the start and end are usually what matters).
MAX_OUTPUT_CHARS = 30_000

# Runs a bash tool command in the directory the previous command ended in, so `cd` persists
# across calls like in an interactive shell. Environment variables do not persist.
_BASH_WRAPPER = r"""
cd "$(cat /tmp/.agent_cwd 2>/dev/null || echo /workspace)" 2>/dev/null || cd /workspace
eval "$1"
status=$?
pwd > /tmp/.agent_cwd 2>/dev/null
exit $status
"""


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False


class Toolbox(Protocol):
    def definitions(self) -> list[dict[str, Any]]:
        """Entries for the request's `tools` parameter."""
        ...

    async def execute(self, name: str, tool_input: Any) -> ToolOutput:
        """Run one client tool call. Must not raise for tool-level failures."""
        ...


class AgentToolbox:
    """The tools enabled on an agent. The sandbox is only started on the first call."""

    def __init__(self, agent: Agent, conversation_id: uuid.UUID, sandboxes: SandboxProvider):
        self._agent = agent
        self._conversation_id = conversation_id
        self._sandboxes = sandboxes
        self._sandbox: Sandbox | None = None

    def definitions(self) -> list[dict[str, Any]]:
        enabled = self._agent.tools
        tools = []
        if enabled.get("bash"):
            tools.append(BASH_TOOL)
        if enabled.get("text_editor"):
            tools.append(EDITOR_TOOL)
        if enabled.get("web_search"):
            tools.append(WEB_SEARCH_TOOL)
        if enabled.get("web_fetch"):
            tools.append(WEB_FETCH_TOOL)
        return tools

    async def execute(self, name: str, tool_input: Any) -> ToolOutput:
        enabled = {t["name"] for t in self.definitions()}
        if name not in enabled:
            return ToolOutput(f"Unknown tool: {name}", is_error=True)
        if not isinstance(tool_input, dict):
            return ToolOutput("Tool input must be an object", is_error=True)
        try:
            sandbox = await self._get_sandbox()
            if name == BASH_TOOL["name"]:
                return await run_bash(sandbox, tool_input)
            return await run_editor(sandbox, tool_input)
        except SandboxError as exc:
            return ToolOutput(str(exc), is_error=True)

    async def _get_sandbox(self) -> Sandbox:
        if self._sandbox is None:
            self._sandbox = await self._sandboxes.get(
                self._conversation_id, network=self._agent.sandbox_network
            )
        return self._sandbox


# =============================================================================
# bash
# =============================================================================


async def run_bash(sandbox: Sandbox, tool_input: dict[str, Any]) -> ToolOutput:
    if tool_input.get("restart"):
        await sandbox.exec(["rm", "-f", "/tmp/.agent_cwd"], timeout=10)
        return ToolOutput("The bash session was restarted (working directory is /workspace).")
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolOutput("`command` must be a non-empty string", is_error=True)

    timeout = get_settings().sandbox_command_timeout_seconds
    result = await sandbox.exec(["bash", "-c", _BASH_WRAPPER, "bash", command], timeout=timeout)
    output = truncate(result.output.rstrip("\n"))
    if result.timed_out:
        return ToolOutput(f"{output}\n[timed out after {timeout}s]".lstrip(), is_error=True)
    if result.exit_code != 0:
        output = f"{output}\n[exit code {result.exit_code}]".lstrip()
    return ToolOutput(output or "(no output)")


# =============================================================================
# str_replace_based_edit_tool
# =============================================================================


async def run_editor(sandbox: Sandbox, tool_input: dict[str, Any]) -> ToolOutput:
    command = tool_input.get("command")
    raw_path = tool_input.get("path")
    if not isinstance(raw_path, str):
        return ToolOutput("`path` must be a string", is_error=True)
    path = in_workspace(raw_path)
    if path is None:
        return ToolOutput(
            f"Paths must be absolute and inside {WORKSPACE}: {raw_path}", is_error=True
        )
    match command:
        case "view":
            return await _view(sandbox, path, tool_input.get("view_range"))
        case "create":
            return await _create(sandbox, path, tool_input.get("file_text"))
        case "str_replace":
            return await _str_replace(
                sandbox, path, tool_input.get("old_str"), tool_input.get("new_str", "")
            )
        case "insert":
            return await _insert(
                sandbox, path, tool_input.get("insert_line"), tool_input.get("insert_text")
            )
        case _:
            return ToolOutput(f"Unknown command: {command}", is_error=True)


async def _view(sandbox: Sandbox, path: str, view_range: Any) -> ToolOutput:
    is_dir = await sandbox.exec(["test", "-d", path], timeout=10)
    if is_dir.exit_code == 0:
        listing = await sandbox.exec(
            ["find", path, "-maxdepth", "2", "-not", "-path", "*/.*"], timeout=30
        )
        lines = sorted(listing.output.splitlines())
        return ToolOutput(truncate("\n".join(lines)) or "(empty directory)")

    text = await _read_text(sandbox, path)
    if isinstance(text, ToolOutput):
        return text
    lines = text.split("\n")
    start, end = 1, len(lines)
    if view_range is not None:
        if (
            not isinstance(view_range, list)
            or len(view_range) != 2
            or not all(isinstance(n, int) for n in view_range)
        ):
            return ToolOutput("`view_range` must be [start, end]", is_error=True)
        start, end = view_range
        if end == -1:
            end = len(lines)
        if not 1 <= start <= end <= len(lines):
            return ToolOutput(
                f"Invalid view_range {view_range}: the file has {len(lines)} lines",
                is_error=True,
            )
    numbered = "\n".join(f"{n:6}\t{lines[n - 1]}" for n in range(start, end + 1))
    return ToolOutput(truncate(numbered))


async def _create(sandbox: Sandbox, path: str, file_text: Any) -> ToolOutput:
    if not isinstance(file_text, str):
        return ToolOutput("`file_text` must be a string", is_error=True)
    await sandbox.write_file(path, file_text.encode())
    return ToolOutput(f"Wrote {path}")


async def _str_replace(sandbox: Sandbox, path: str, old: Any, new: Any) -> ToolOutput:
    if not isinstance(old, str) or old == "":
        return ToolOutput("`old_str` must be a non-empty string", is_error=True)
    if not isinstance(new, str):
        return ToolOutput("`new_str` must be a string", is_error=True)
    text = await _read_text(sandbox, path)
    if isinstance(text, ToolOutput):
        return text
    count = text.count(old)
    if count == 0:
        return ToolOutput(f"No match for `old_str` in {path}", is_error=True)
    if count > 1:
        return ToolOutput(
            f"`old_str` matches {count} times in {path}; include more context to make it unique",
            is_error=True,
        )
    await sandbox.write_file(path, text.replace(old, new, 1).encode())
    return ToolOutput(f"Edited {path}")


async def _insert(sandbox: Sandbox, path: str, line: Any, insert_text: Any) -> ToolOutput:
    if not isinstance(insert_text, str):
        return ToolOutput("`insert_text` must be a string", is_error=True)
    text = await _read_text(sandbox, path)
    if isinstance(text, ToolOutput):
        return text
    lines = text.split("\n")
    if not isinstance(line, int) or not 0 <= line <= len(lines):
        return ToolOutput(
            f"`insert_line` must be between 0 and {len(lines)} for {path}", is_error=True
        )
    lines[line:line] = insert_text.split("\n")
    await sandbox.write_file(path, "\n".join(lines).encode())
    return ToolOutput(f"Inserted text after line {line} of {path}")


async def _read_text(sandbox: Sandbox, path: str) -> str | ToolOutput:
    try:
        data = await sandbox.read_file(path)
    except FileNotFoundError:
        return ToolOutput(f"No such file: {path}", is_error=True)
    except IsADirectoryError:
        return ToolOutput(f"{path} is a directory", is_error=True)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolOutput(f"{path} is not a UTF-8 text file", is_error=True)


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n… [{omitted} characters omitted] …\n{text[-half:]}"
