"""AnthropicLLM against a canned Messages API stream (no network)."""

import json

import httpx2
from anthropic import AsyncAnthropic

from app.services.runtime.llm import AnthropicLLM, TurnRequest


def _sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


_STREAM = _sse(
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1, "cache_read_input_tokens": 4},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "thinking", "thinking": "", "signature": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "Considering"},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "signature_delta", "signature": "sig=="},
    },
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Hel"}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "lo"}},
    {"type": "content_block_stop", "index": 1},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 7},
    },
    {"type": "message_stop"},
)


def _client(requests: list[dict]) -> AsyncAnthropic:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(
            {
                "body": json.loads(request.content),
                "beta": request.headers.get("anthropic-beta", ""),
            }
        )
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=_STREAM
        )

    return AsyncAnthropic(
        api_key="test-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )


async def test_streams_deltas_and_returns_replayable_content():
    requests: list[dict] = []
    deltas: list[tuple[str, str]] = []

    async def on_delta(kind, text):
        deltas.append((kind, text))

    async def on_reset():
        raise AssertionError("no fallback in this stream")

    result = await AnthropicLLM(_client(requests)).run_turn(
        TurnRequest(
            model="claude-opus-5-5",
            effort="high",
            system="Be brief",
            messages=[{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
        ),
        on_delta=on_delta,
        on_reset=on_reset,
    )

    assert deltas == [("thinking", "Considering"), ("text", "Hel"), ("text", "lo")]
    assert result.content == [
        {"type": "thinking", "thinking": "Considering", "signature": "sig=="},
        {"type": "text", "text": "Hello"},
    ]
    assert result.stop_reason == "end_turn"
    assert result.stop_details is None
    assert (result.input_tokens, result.output_tokens, result.cache_read_input_tokens) == (12, 7, 4)

    body = requests[0]["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "Be brief"
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "high"}
    assert body["fallbacks"] == "default"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"] == [{"type": "web_search_20260209", "name": "web_search"}]
    assert body["stream"] is True
    assert "server-side-fallback-2026-07-01" in requests[0]["beta"]


async def test_haiku_requests_have_no_fallbacks():
    requests: list[dict] = []

    async def noop(*_):
        return None

    await AnthropicLLM(_client(requests)).run_turn(
        TurnRequest(
            model="claude-haiku-5-5",
            effort="low",
            system=None,
            messages=[{"role": "user", "content": "Hi"}],
        ),
        on_delta=noop,
        on_reset=noop,
    )
    body = requests[0]["body"]
    assert "fallbacks" not in body
    assert "system" not in body
    assert "tools" not in body
    assert "server-side-fallback" not in requests[0]["beta"]
