"""The model call behind one agent turn.

`LLM` is the seam the agent loop depends on; `AnthropicLLM` streams from the Messages API
and tests substitute a scripted fake.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from anthropic import AsyncAnthropic

from app.config import get_settings

DeltaKind = Literal["text", "thinking"]
OnDelta = Callable[[DeltaKind, str], Awaitable[None]]
# Called when output streamed so far for this turn must be discarded
# (a fallback model took over, or the turn was refused mid-stream).
OnReset = Callable[[], Awaitable[None]]

# Models that accept `fallbacks: "default"`; Claude Haiku 5.5 has no server-side fallback.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_MAX_TOKENS = 64_000


@dataclass
class TurnRequest:
    model: str
    effort: str
    system: str | None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    betas: list[str] = field(default_factory=list)


@dataclass
class TurnResult:
    # Content blocks as JSON, ready to be stored and replayed unchanged.
    content: list[dict[str, Any]]
    stop_reason: str | None
    stop_details: dict[str, Any] | None
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int


class LLM(Protocol):
    async def run_turn(
        self, request: TurnRequest, *, on_delta: OnDelta, on_reset: OnReset
    ) -> TurnResult: ...


class AnthropicLLM:
    """Uses ANTHROPIC_API_KEY from the settings (.env), else the SDK's own credential lookup."""

    def __init__(self, client: AsyncAnthropic | None = None):
        if client is None:
            api_key = get_settings().anthropic_api_key
            client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
        self._client = client

    async def run_turn(
        self, request: TurnRequest, *, on_delta: OnDelta, on_reset: OnReset
    ) -> TurnResult:
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": _MAX_TOKENS,
            "messages": request.messages,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": request.effort},
            # Caches tools + system + history up to the last message.
            "cache_control": {"type": "ephemeral"},
        }
        if request.system:
            params["system"] = request.system
        if request.tools:
            params["tools"] = request.tools
        if request.mcp_servers:
            params["mcp_servers"] = request.mcp_servers
        betas = list(request.betas)
        if request.model in _FALLBACK_MODELS:
            params["fallbacks"] = "default"
            betas.append(_FALLBACK_BETA)

        async with self._client.beta.messages.stream(**params, betas=betas) as stream:
            async for event in stream:
                if event.type == "content_block_start" and event.content_block.type == "fallback":
                    await on_reset()
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        await on_delta("text", event.delta.text)
                    elif event.delta.type == "thinking_delta":
                        await on_delta("thinking", event.delta.thinking)
            message = await stream.get_final_message()

        usage = message.usage
        return TurnResult(
            content=[block.model_dump(mode="json", exclude_none=True) for block in message.content],
            stop_reason=message.stop_reason,
            stop_details=(
                message.stop_details.model_dump(mode="json") if message.stop_details else None
            ),
            model=message.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        )
