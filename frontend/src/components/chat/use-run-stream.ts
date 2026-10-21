"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { streamRunEvents } from "@/lib/api/run-events";
import { conversationKeys, runKeys } from "@/lib/queries/conversations";

export type ToolResult = { output: string; isError: boolean };

/** What the active run has produced that is not yet part of the stored transcript. */
export type LiveRun = {
  // Output of the turn being generated; cleared once the turn is stored as a message.
  thinking: string;
  text: string;
  // Results of client tools, shown before the result message is stored.
  toolResults: Record<string, ToolResult>;
};

const EMPTY: LiveRun = { thinking: "", text: "", toolResults: {} };

/**
 * Follows a run's event stream while it is active. Stored messages are refetched as the
 * worker persists them, so the live state only ever holds the in-progress turn.
 */
export function useRunStream(conversationId: string, runId: string | null): LiveRun {
  const queryClient = useQueryClient();
  // Keyed by run so a new run starts from an empty state without resetting in the effect.
  const [state, setState] = useState<{ runId: string | null; live: LiveRun }>({
    runId: null,
    live: EMPTY,
  });

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    const update = (fn: (live: LiveRun) => LiveRun) =>
      setState((prev) => ({ runId, live: fn(prev.runId === runId ? prev.live : EMPTY) }));
    const refetchConversation = () =>
      queryClient.refetchQueries({ queryKey: conversationKeys.detail(conversationId) });

    streamRunEvents(runId, {
      signal: controller.signal,
      onEvent: async (event) => {
        switch (event.type) {
          case "text_delta":
            update((live) => ({ ...live, text: live.text + event.data.text }));
            break;
          case "thinking_delta":
            update((live) => ({ ...live, thinking: live.thinking + event.data.text }));
            break;
          case "turn_reset":
            update((live) => ({ ...live, text: "", thinking: "" }));
            break;
          case "tool_result":
            update((live) => ({
              ...live,
              toolResults: {
                ...live.toolResults,
                [event.data.id]: { output: event.data.output, isError: event.data.isError },
              },
            }));
            break;
          case "message":
            // Show the stored message before dropping the streamed copy (no flicker).
            await refetchConversation();
            update((live) => ({ ...live, text: "", thinking: "" }));
            break;
          case "run_finished":
            await refetchConversation();
            update(() => EMPTY);
            if (event.data.status === "failed" && event.data.error) {
              toast.error(event.data.error);
            } else if (event.data.status === "cancelled") {
              toast.info("Stopped");
            }
            break;
        }
      },
    })
      .catch((error: Error) => toast.error(error.message))
      .finally(() => {
        if (controller.signal.aborted) return;
        void queryClient.invalidateQueries({ queryKey: conversationKeys.all });
        void queryClient.invalidateQueries({ queryKey: runKeys.all });
      });

    return () => controller.abort();
  }, [conversationId, runId, queryClient]);

  return state.runId === runId ? state.live : EMPTY;
}
