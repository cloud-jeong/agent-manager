"use client";

import {
  ArrowRightLeft,
  Brain,
  ChevronRight,
  Globe,
  Loader2,
  Plug,
  Search,
  SquareTerminal,
  Wrench,
} from "lucide-react";

import { Markdown } from "@/components/chat/markdown";
import type { ToolResult } from "@/components/chat/use-run-stream";
import { cn } from "@/lib/utils";

/** A content block in Messages API shape, as stored by the backend. */
export type Block = { type: string; [key: string]: unknown };

/** Renders one assistant content block. `results` maps tool_use ids to their results. */
export function AssistantBlock({
  block,
  results,
  running,
}: {
  block: Block;
  results: Record<string, ToolResult>;
  running: boolean;
}) {
  switch (block.type) {
    case "text":
      return <Markdown>{String(block.text ?? "")}</Markdown>;
    case "thinking":
      return block.thinking ? <ThinkingBlock text={String(block.thinking)} /> : null;
    case "tool_use":
      return (
        <ToolCall
          name={String(block.name)}
          input={block.input}
          result={results[String(block.id)]}
          pending={running}
        />
      );
    case "server_tool_use":
      return <ServerToolCall name={String(block.name)} input={block.input} />;
    case "web_search_tool_result":
      return <WebSearchResults content={block.content} />;
    case "mcp_tool_use":
      return (
        <ToolCall
          name={`${String(block.server_name)} · ${String(block.name)}`}
          input={block.input}
          result={results[String(block.id)]}
          pending={running}
          icon={Plug}
        />
      );
    case "fallback":
      return <FallbackNotice block={block} />;
    default:
      // web_fetch_tool_result, mcp_tool_result, redacted_thinking, ...: nothing to show
      // on their own (results are attached to their tool call).
      return null;
  }
}

export function ThinkingBlock({ text, live = false }: { text: string; live?: boolean }) {
  return (
    <details className="group rounded-md border bg-muted/30 text-sm" open={live}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-1.5 text-muted-foreground select-none">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
        <Brain className="size-3.5" />
        {live ? "Thinking…" : "Thought process"}
      </summary>
      <div className="border-t px-3 py-2 whitespace-pre-wrap text-muted-foreground">{text}</div>
    </details>
  );
}

function ToolCall({
  name,
  input,
  result,
  pending,
  icon,
}: {
  name: string;
  input: unknown;
  result: ToolResult | undefined;
  pending: boolean;
  icon?: typeof Wrench;
}) {
  const Icon = icon ?? (name === "bash" ? SquareTerminal : Wrench);
  const summary = toolSummary(name, input);
  return (
    <details className="group rounded-md border text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 select-none">
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="font-medium">{toolLabel(name)}</span>
        {summary && <code className="truncate text-xs text-muted-foreground">{summary}</code>}
        <span className="ml-auto shrink-0">
          {result ? (
            result.isError && <span className="text-xs text-destructive">error</span>
          ) : pending ? (
            <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
          ) : null}
        </span>
      </summary>
      <div className="space-y-2 border-t px-3 py-2">
        <Code label="Input">{formatInput(name, input)}</Code>
        {result && (
          <Code label={result.isError ? "Error" : "Output"} error={result.isError}>
            {result.output || "(no output)"}
          </Code>
        )}
      </div>
    </details>
  );
}

function ServerToolCall({ name, input }: { name: string; input: unknown }) {
  const args = (input ?? {}) as Record<string, unknown>;
  const Icon = name === "web_search" ? Search : Globe;
  const text =
    name === "web_search"
      ? `Searched the web for “${String(args.query ?? "")}”`
      : name === "web_fetch"
        ? `Fetched ${String(args.url ?? "")}`
        : name;
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Icon className="size-3.5 shrink-0" />
      <span className="truncate">{text}</span>
    </div>
  );
}

function WebSearchResults({ content }: { content: unknown }) {
  if (!Array.isArray(content)) {
    const code = (content as { error_code?: string } | null)?.error_code;
    return <p className="text-sm text-destructive">Web search failed{code ? `: ${code}` : ""}</p>;
  }
  const results = content as { url: string; title?: string }[];
  if (results.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {results.slice(0, 8).map((r) => (
        <li key={r.url}>
          <a
            href={r.url}
            target="_blank"
            rel="noreferrer"
            className="block max-w-64 truncate rounded-full border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted"
            title={r.url}
          >
            {r.title || new URL(r.url).hostname}
          </a>
        </li>
      ))}
    </ul>
  );
}

function FallbackNotice({ block }: { block: Block }) {
  const from = (block.from as { model?: string } | undefined)?.model;
  const to = (block.to as { model?: string } | undefined)?.model;
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <ArrowRightLeft className="size-3" />
      {from ?? "The model"} declined; {to ?? "a fallback model"} continued.
    </p>
  );
}

function Code({
  label,
  children,
  error = false,
}: {
  label: string;
  children: string;
  error?: boolean;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
      <pre
        className={cn(
          "max-h-80 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre-wrap",
          error && "text-destructive",
        )}
      >
        {children}
      </pre>
    </div>
  );
}

const TOOL_LABELS: Record<string, string> = {
  bash: "Bash",
  str_replace_based_edit_tool: "File editor",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

function toolSummary(name: string, input: unknown): string {
  const args = (input ?? {}) as Record<string, unknown>;
  if (name === "bash") return args.restart ? "restart" : String(args.command ?? "");
  if (name === "str_replace_based_edit_tool") {
    return `${String(args.command ?? "")} ${String(args.path ?? "")}`.trim();
  }
  return "";
}

function formatInput(name: string, input: unknown): string {
  const args = (input ?? {}) as Record<string, unknown>;
  if (name === "bash" && typeof args.command === "string") return args.command;
  return JSON.stringify(input, null, 2);
}

/** Text of a tool_result block's content (a string or a list of text blocks). */
export function toolResultText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (part && typeof part === "object" && "text" in part ? String(part.text) : ""))
      .join("\n");
  }
  return "";
}
