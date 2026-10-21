// Client for `GET /api/runs/{id}/events` (server-sent events).
// EventSource cannot send an Authorization header, so the stream is read with fetch.
// Network failures reconnect from the last received event id.

import { API_URL, ApiError, type RunStatus } from "@/lib/api/client";
import { clearToken, getToken } from "@/lib/auth";

export type RunEvent =
  | { type: "run_started"; data: { model: string } }
  | { type: "text_delta"; data: { text: string } }
  | { type: "thinking_delta"; data: { text: string } }
  | { type: "turn_reset"; data: Record<string, never> }
  | { type: "tool_call"; data: { id: string; name: string; input: unknown } }
  | { type: "tool_result"; data: { id: string; output: string; isError: boolean } }
  | { type: "message"; data: { messageId: string } }
  | {
      type: "usage";
      data: {
        model: string;
        inputTokens: number;
        outputTokens: number;
        cacheReadInputTokens: number;
      };
    }
  | { type: "run_finished"; data: { status: RunStatus; error: string | null } }
  | { type: "done"; data: { status: RunStatus | "deleted" } };

const MAX_BACKOFF_MS = 10_000;

/** Stream a run's events until the server sends `done` or `signal` aborts. */
export async function streamRunEvents(
  runId: string,
  {
    signal,
    onEvent,
  }: {
    signal: AbortSignal;
    onEvent: (event: RunEvent) => void | Promise<void>;
  },
): Promise<void> {
  let lastId: number | undefined;
  for (let attempt = 0; !signal.aborted; attempt++) {
    try {
      const query = lastId === undefined ? "" : `?after=${lastId}`;
      const token = getToken();
      const response = await fetch(`${API_URL}/api/runs/${runId}/events${query}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal,
      });
      if (response.status === 401) clearToken();
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, response.statusText || "Could not stream the run");
      }
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        attempt = 0;
        buffer += value;
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const parsed = parseEvent(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (!parsed) continue;
          if (parsed.id !== undefined) lastId = parsed.id;
          await onEvent(parsed.event);
          if (parsed.event.type === "done") return;
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      // Client errors (404, 401) will not fix themselves.
      if (error instanceof ApiError && error.status < 500) throw error;
    }
    await sleep(Math.min(500 * 2 ** attempt, MAX_BACKOFF_MS), signal);
  }
}

function parseEvent(chunk: string): { id?: number; event: RunEvent } | null {
  let id: number | undefined;
  let type: string | undefined;
  const data: string[] = [];
  for (const line of chunk.split("\n")) {
    if (line.startsWith(":")) continue; // keepalive comment
    const colon = line.indexOf(":");
    if (colon < 0) continue;
    const field = line.slice(0, colon);
    const value = line.slice(colon + 1).replace(/^ /, "");
    if (field === "id") id = Number(value);
    else if (field === "event") type = value;
    else if (field === "data") data.push(value);
  }
  if (!type) return null;
  return { id, event: { type, data: JSON.parse(data.join("\n") || "{}") } as RunEvent };
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}
