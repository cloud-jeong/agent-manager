"""Test doubles for the runtime: a scripted model and a recording toolbox."""

import asyncio
import copy
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.runtime.llm import OnDelta, OnReset, TurnRequest, TurnResult
from app.services.runtime.tools import ToolOutput


def text_turn(text: str, *, stop_reason: str = "end_turn") -> TurnResult:
    return turn([{"type": "text", "text": text}], stop_reason=stop_reason)


def tool_turn(*calls: tuple[str, str, dict[str, Any]], text: str | None = None) -> TurnResult:
    """A turn calling tools: each call is `(id, name, input)`."""
    content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    content += [{"type": "tool_use", "id": id_, "name": name, "input": i} for id_, name, i in calls]
    return turn(content, stop_reason="tool_use")


def turn(
    content: list[dict[str, Any]],
    *,
    stop_reason: str = "end_turn",
    stop_details: dict[str, Any] | None = None,
) -> TurnResult:
    return TurnResult(
        content=content,
        stop_reason=stop_reason,
        stop_details=stop_details,
        model="claude-opus-5-5",
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=2,
    )


# A scripted step is a result, or a coroutine function producing one (to block, raise, ...).
Step = TurnResult | Callable[[], Awaitable[TurnResult]]


class FakeLLM:
    def __init__(self, *steps: Step):
        self._steps = list(steps)
        self.requests: list[TurnRequest] = []

    async def run_turn(
        self, request: TurnRequest, *, on_delta: OnDelta, on_reset: OnReset
    ) -> TurnResult:
        # Snapshot: the executor keeps appending to the same history list.
        self.requests.append(copy.deepcopy(request))
        if not self._steps:
            raise AssertionError("FakeLLM ran out of scripted turns")
        step = self._steps.pop(0)
        result = step if isinstance(step, TurnResult) else await step()
        for block in result.content:
            if block.get("type") == "text":
                await on_delta("text", block["text"])
        return result


async def block_forever() -> TurnResult:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


class RecordingToolbox:
    def __init__(self, outputs: dict[str, ToolOutput] | None = None):
        self.calls: list[tuple[str, Any]] = []
        self._outputs = outputs or {}

    def definitions(self) -> list[dict[str, Any]]:
        return [{"name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]

    async def execute(self, name: str, tool_input: Any) -> ToolOutput:
        self.calls.append((name, tool_input))
        return self._outputs.get(name, ToolOutput(f"ran {name}"))
