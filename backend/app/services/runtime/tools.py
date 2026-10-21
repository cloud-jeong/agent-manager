"""Tools offered to the model for one run, and execution of client-side tool calls.

Server tools (web search/fetch) run on Anthropic and only need a definition.
Client tools are executed here; their results go back to the model as `tool_result`.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from app.models import Agent

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}
WEB_FETCH_TOOL = {"type": "web_fetch_20260209", "name": "web_fetch"}


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


class ServerToolbox:
    """Only server tools: nothing executes locally."""

    def __init__(self, agent: Agent):
        self._agent = agent

    def definitions(self) -> list[dict[str, Any]]:
        return server_tool_definitions(self._agent)

    async def execute(self, name: str, tool_input: Any) -> ToolOutput:
        return ToolOutput(f"Unknown tool: {name}", is_error=True)


def server_tool_definitions(agent: Agent) -> list[dict[str, Any]]:
    tools = []
    if agent.tools.get("web_search"):
        tools.append(WEB_SEARCH_TOOL)
    if agent.tools.get("web_fetch"):
        tools.append(WEB_FETCH_TOOL)
    return tools
