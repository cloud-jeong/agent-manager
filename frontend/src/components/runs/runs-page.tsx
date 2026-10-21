"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { API_URL, type Run, type RunStatus } from "@/lib/api/client";
import { type RunListParams, useCancelRun, useRuns } from "@/lib/queries/conversations";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;
const ALL = "all";

export function RunsPage() {
  return <AppShell>{() => <RunsList />}</AppShell>;
}

function RunsList() {
  const [status, setStatus] = useState<string>(ALL);
  const [trigger, setTrigger] = useState<string>(ALL);
  const [page, setPage] = useState(0);
  const cancel = useCancelRun();

  const params: RunListParams = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(status !== ALL && { status: status as RunStatus }),
    ...(trigger !== ALL && { trigger: trigger as Run["trigger"] }),
  };
  const runs = useRuns(params);
  const total = runs.data?.pagination.total ?? 0;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Runs</h1>
        <p className="text-sm text-muted-foreground">
          Every agent execution you started, from chat or from the API.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <FilterSelect
          label="Status"
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(0);
          }}
          items={[
            { value: ALL, label: "All statuses" },
            ...(["queued", "running", "succeeded", "failed", "cancelled"] as const).map((s) => ({
              value: s,
              label: STATUS_LABELS[s],
            })),
          ]}
        />
        <FilterSelect
          label="Trigger"
          value={trigger}
          onChange={(v) => {
            setTrigger(v);
            setPage(0);
          }}
          items={[
            { value: ALL, label: "Chat and API" },
            { value: "chat", label: "Chat" },
            { value: "api", label: "API" },
          ]}
        />
      </div>

      {runs.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : total === 0 ? (
        <EmptyState />
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead className="text-right">Tokens (in / out)</TableHead>
                <TableHead className="text-right">Duration</TableHead>
                <TableHead>Started</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.data?.data.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <StatusBadge status={run.status} />
                    {run.error && (
                      <p className="mt-1 max-w-xs truncate text-xs text-destructive" title={run.error}>
                        {run.error}
                      </p>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">
                    {run.agent.icon ?? "🤖"} {run.agent.name}
                  </TableCell>
                  <TableCell className="text-sm">
                    {run.trigger === "api" ? "API" : "Chat"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {run.inputTokens.toLocaleString()} / {run.outputTokens.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right text-sm text-muted-foreground">
                    {formatDuration(run)}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {new Date(run.createdAt).toLocaleString()}
                  </TableCell>
                  <TableCell className="space-x-1 text-right">
                    {(run.status === "queued" || run.status === "running") && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={cancel.isPending}
                        onClick={() =>
                          cancel.mutate(run.id, {
                            onSuccess: () => runs.refetch(),
                            onError: (e) => toast.error(e.message),
                          })
                        }
                      >
                        Stop
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      nativeButton={false}
                      render={<Link href={`/chat/${run.conversationId}`} />}
                    >
                      Open
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!runs.data?.pagination.hasNext}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  items,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  items: { value: string; label: string }[];
}) {
  return (
    <Select value={value} onValueChange={(v) => v && onChange(v)} items={items}>
      <SelectTrigger className="w-44" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

const STATUS_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        status === "succeeded" && "border-emerald-500/40 text-emerald-700 dark:text-emerald-400",
        status === "failed" && "border-destructive/40 text-destructive",
        (status === "running" || status === "queued") &&
          "border-sky-500/40 text-sky-700 dark:text-sky-400",
      )}
    >
      {STATUS_LABELS[status]}
    </Badge>
  );
}

function formatDuration(run: Run): string {
  if (!run.startedAt) return "—";
  const end = run.finishedAt ? new Date(run.finishedAt) : new Date();
  const seconds = Math.max(0, (end.getTime() - new Date(run.startedAt).getTime()) / 1000);
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function EmptyState() {
  return (
    <div className="space-y-3 rounded-lg border p-6 text-sm">
      <p className="text-muted-foreground">
        No runs yet. Start a chat, or run an agent in the background through the API:
      </p>
      <pre className="overflow-x-auto rounded bg-muted p-3 font-mono text-xs">
        {`curl -X POST ${API_URL}/api/agents/<agent id>/runs \\
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \\
  -d '{"input": "Summarize the open issues"}'

# then poll the result
curl ${API_URL}/api/runs/<run id> -H "Authorization: Bearer <token>"`}
      </pre>
    </div>
  );
}
