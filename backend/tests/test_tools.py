"""The bash and file editor tools against an in-memory sandbox."""

import uuid
from types import SimpleNamespace

from app.services.runtime.sandbox import ExecResult, in_workspace
from app.services.runtime.tools import (
    BASH_TOOL,
    EDITOR_TOOL,
    WEB_SEARCH_TOOL,
    AgentToolbox,
    truncate,
)
from tests.fakes import FakeSandboxProvider

CONVERSATION = uuid.uuid4()


def _toolbox(**tools):
    agent = SimpleNamespace(tools=tools, sandbox_network=False)
    provider = FakeSandboxProvider()
    toolbox = AgentToolbox(agent, CONVERSATION, provider)  # type: ignore[arg-type]
    return toolbox, provider


def _sandbox(provider):
    return provider.sandboxes[CONVERSATION]


async def _edit(toolbox, **tool_input):
    return await toolbox.execute(EDITOR_TOOL["name"], tool_input)


def test_definitions_follow_agent_settings():
    assert _toolbox()[0].definitions() == []
    toolbox, _ = _toolbox(bash=True, text_editor=False, web_search=True)
    assert toolbox.definitions() == [BASH_TOOL, WEB_SEARCH_TOOL]


async def test_disabled_tool_is_rejected_without_starting_a_sandbox():
    toolbox, provider = _toolbox(text_editor=True)
    result = await toolbox.execute("bash", {"command": "ls"})
    assert result.is_error
    assert provider.requests == []


async def test_bash_runs_in_wrapper_and_reports_exit_code():
    toolbox, provider = _toolbox(bash=True)
    result = await toolbox.execute("bash", {"command": "ls /workspace"})
    assert result.content == "ok"
    argv = _sandbox(provider).commands[0]
    assert argv[:2] == ["bash", "-c"]
    assert argv[-1] == "ls /workspace"

    _sandbox(provider).results.append(ExecResult(2, "ls: cannot access 'x'\n"))
    result = await toolbox.execute("bash", {"command": "ls x"})
    assert not result.is_error
    assert result.content == "ls: cannot access 'x'\n[exit code 2]"


async def test_bash_timeout_and_restart():
    toolbox, provider = _toolbox(bash=True)
    await toolbox.execute("bash", {"command": "true"})
    _sandbox(provider).results.append(ExecResult(124, "", timed_out=True))
    result = await toolbox.execute("bash", {"command": "sleep 999"})
    assert result.is_error
    assert "timed out" in result.content

    result = await toolbox.execute("bash", {"restart": True})
    assert "restarted" in result.content
    assert _sandbox(provider).commands[-1] == ["rm", "-f", "/tmp/.agent_cwd"]


async def test_sandbox_is_reused_within_a_run():
    toolbox, provider = _toolbox(bash=True)
    await toolbox.execute("bash", {"command": "a"})
    await toolbox.execute("bash", {"command": "b"})
    assert provider.requests == [(CONVERSATION, False)]


async def test_editor_create_view_replace_insert():
    toolbox, provider = _toolbox(text_editor=True)
    path = "/workspace/src/app.py"

    assert not (
        await _edit(toolbox, command="create", path=path, file_text="a = 1\nb = 2")
    ).is_error
    assert _sandbox(provider).files[path] == b"a = 1\nb = 2"

    view = await _edit(toolbox, command="view", path=path)
    assert view.content == "     1\ta = 1\n     2\tb = 2"
    view = await _edit(toolbox, command="view", path=path, view_range=[2, -1])
    assert view.content == "     2\tb = 2"

    result = await _edit(
        toolbox, command="str_replace", path=path, old_str="b = 2", new_str="b = 3"
    )
    assert not result.is_error
    assert _sandbox(provider).files[path] == b"a = 1\nb = 3"

    result = await _edit(toolbox, command="insert", path=path, insert_line=0, insert_text="# hi")
    assert not result.is_error
    assert _sandbox(provider).files[path] == b"# hi\na = 1\nb = 3"

    listing = await _edit(toolbox, command="view", path="/workspace")
    assert listing.content == path


async def test_editor_errors():
    toolbox, provider = _toolbox(text_editor=True)
    path = "/workspace/x.txt"
    await _edit(toolbox, command="create", path=path, file_text="dup dup")

    cases = [
        {"command": "view", "path": "/workspace/missing.txt"},
        {"command": "view", "path": path, "view_range": [3, 4]},
        {"command": "str_replace", "path": path, "old_str": "dup", "new_str": "x"},
        {"command": "str_replace", "path": path, "old_str": "nope", "new_str": "x"},
        {"command": "insert", "path": path, "insert_line": 9, "insert_text": "x"},
        {"command": "undo_edit", "path": path},
        {"command": "view", "path": "/etc/passwd"},
        {"command": "view", "path": "/workspace/../etc/passwd"},
        {"command": "create", "path": "relative.txt", "file_text": "x"},
    ]
    for case in cases:
        assert (await _edit(toolbox, **case)).is_error, case
    assert _sandbox(provider).files == {path: b"dup dup"}


def test_in_workspace():
    assert in_workspace("/workspace") == "/workspace"
    assert in_workspace("/workspace/a/../b") == "/workspace/b"
    assert in_workspace("/workspace/../etc") is None
    assert in_workspace("/workspacex/a") is None
    assert in_workspace("workspace/a") is None


def test_truncate_keeps_head_and_tail():
    text = "a" * 50 + "b" * 50
    cut = truncate(text, limit=20)
    assert cut.startswith("a" * 10) and cut.endswith("b" * 10)
    assert "80 characters omitted" in cut
    assert truncate("short") == "short"
