"use client";

import { Loader2 } from "lucide-react";
import { useMemo } from "react";

import { Markdown } from "@/components/chat/markdown";
import {
  AssistantBlock,
  type Block,
  ThinkingBlock,
  toolResultText,
} from "@/components/chat/message-blocks";
import type { LiveRun, ToolResult } from "@/components/chat/use-run-stream";
import type { ChatMessage } from "@/lib/api/client";

/**
 * The transcript plus the in-progress turn of the active run.
 *
 * Tool results live in separate messages in the API transcript (user `tool_result`
 * blocks, or `mcp_tool_result` blocks); here they are shown inside their tool call.
 */
export function MessageList({
  messages,
  live,
  running,
}: {
  messages: ChatMessage[];
  live: LiveRun;
  running: boolean;
}) {
  const results = useMemo(() => {
    const stored: Record<string, ToolResult> = {};
    for (const message of messages) {
      for (const block of message.content as Block[]) {
        if (block.type === "tool_result" || block.type === "mcp_tool_result") {
          stored[String(block.tool_use_id)] = {
            output: toolResultText(block.content),
            isError: Boolean(block.is_error),
          };
        }
      }
    }
    return { ...live.toolResults, ...stored };
  }, [messages, live.toolResults]);

  const hasLiveOutput = live.text !== "" || live.thinking !== "";

  return (
    <div className="space-y-6">
      {messages.map((message) => {
        const blocks = message.content as Block[];
        if (message.role === "user") {
          const text = blocks
            .filter((b) => b.type === "text")
            .map((b) => String(b.text))
            .join("\n\n");
          // Messages carrying only tool results are rendered inside the tool calls.
          if (!text) return null;
          return (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2 text-sm whitespace-pre-wrap">
                {text}
              </div>
            </div>
          );
        }
        return (
          <div key={message.id} className="space-y-3">
            {blocks.map((block, i) => (
              <AssistantBlock key={i} block={block} results={results} running={running} />
            ))}
          </div>
        );
      })}

      {running && (
        <div className="space-y-3">
          {live.thinking && <ThinkingBlock text={live.thinking} live />}
          {live.text && <Markdown>{live.text}</Markdown>}
          {!hasLiveOutput && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Working…
            </div>
          )}
        </div>
      )}
    </div>
  );
}
