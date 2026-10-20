"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import {
  type AgentFilters,
  AgentsToolbar,
  parseLabelFilter,
  serializeLabelFilter,
} from "@/components/agents/agents-toolbar";
import { AgentsTable, type SortBy, type SortDirection } from "@/components/agents/agents-table";
import { DeleteAgentDialog } from "@/components/agents/delete-agent-dialog";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Agent } from "@/lib/api/client";
import {
  type AgentListParams,
  useAgentsPaginated,
  useDefaultAgentId,
  useDeleteAgent,
  usePurgeAgent,
  useRestoreAgent,
  useSetDefaultAgentId,
} from "@/lib/queries/agents";
import { useTeams } from "@/lib/queries/teams";

const PAGE_SIZE = 20;

export function AgentsListPage() {
  return <AppShell>{() => <AgentsList />}</AppShell>;
}

function AgentsList() {
  const { filters, sortBy, sortDirection, page, update } = useUrlState();
  const teams = useTeams();
  const defaultAgentId = useDefaultAgentId();
  const setDefault = useSetDefaultAgentId();
  const deleteAgent = useDeleteAgent();
  const restoreAgent = useRestoreAgent();
  const purgeAgent = usePurgeAgent();
  const [toDelete, setToDelete] = useState<Agent | null>(null);
  const [toPurge, setToPurge] = useState<Agent | null>(null);

  const params: AgentListParams = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    sortBy,
    sortDirection,
    status: filters.status,
    ...(filters.name && { name: filters.name }),
    ...(filters.scope && { scope: filters.scope as AgentListParams["scope"] }),
    ...(filters.teamId && { teamIds: filters.teamId }),
    ...(Object.keys(filters.labels).length && { labels: serializeLabelFilter(filters.labels) }),
  };
  const agents = useAgentsPaginated(params);
  const deletedView = filters.status === "deleted";
  const total = agents.data?.pagination.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{deletedView ? "Deleted agents" : "Agents"}</h1>
          <p className="text-sm text-muted-foreground">
            {deletedView
              ? "Deleted agents can be restored or removed permanently."
              : "Agents you can see: your own, your teams', shared with you, and organization-wide."}
          </p>
        </div>
        <Button render={<Link href="/agents/new" />}>
          <Plus className="size-4" />
          New agent
        </Button>
      </div>

      <AgentsToolbar
        filters={filters}
        onChange={(patch) => update({ ...patch, page: 0 })}
        teams={teams.data ?? []}
      />

      {agents.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : agents.isError ? (
        <p className="text-sm text-destructive">{agents.error.message}</p>
      ) : agents.data.data.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          {deletedView ? "No deleted agents." : "No agents match these filters."}
        </div>
      ) : (
        <AgentsTable
          agents={agents.data.data}
          deletedView={deletedView}
          defaultAgentId={defaultAgentId.data ?? null}
          sortBy={sortBy}
          sortDirection={sortDirection}
          onSort={(column) =>
            update({
              sortBy: column,
              sortDirection:
                sortBy === column && sortDirection === "asc"
                  ? "desc"
                  : sortBy === column
                    ? "asc"
                    : column === "createdAt"
                      ? "desc"
                      : "asc",
            })
          }
          onDelete={setToDelete}
          onPurge={setToPurge}
          onRestore={(agent) =>
            restoreAgent.mutate(agent.id, {
              onSuccess: () => toast.success(`Restored “${agent.name}”`),
              onError: (e) => toast.error(e.message),
            })
          }
          onToggleDefault={(agent) =>
            setDefault.mutate(agent.id === defaultAgentId.data ? null : agent.id, {
              onError: (e) => toast.error(e.message),
            })
          }
        />
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
              onClick={() => update({ page: page - 1 })}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!agents.data?.pagination.hasNext}
              onClick={() => update({ page: page + 1 })}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <DeleteAgentDialog
        agent={toDelete}
        pending={deleteAgent.isPending}
        onOpenChange={(open) => !open && setToDelete(null)}
        onConfirm={(agent) =>
          deleteAgent.mutate(agent.id, {
            onSuccess: () => {
              setToDelete(null);
              toast.success(`Deleted “${agent.name}”`);
            },
            onError: (e) => toast.error(e.message),
          })
        }
      />
      <DeleteAgentDialog
        agent={toPurge}
        permanent
        pending={purgeAgent.isPending}
        onOpenChange={(open) => !open && setToPurge(null)}
        onConfirm={(agent) =>
          purgeAgent.mutate(agent.id, {
            onSuccess: () => {
              setToPurge(null);
              toast.success(`Permanently deleted “${agent.name}”`);
            },
            onError: (e) => toast.error(e.message),
          })
        }
      />
    </div>
  );
}

/** Filters, sorting and page live in the URL so views are shareable and survive reloads. */
function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const filters: AgentFilters = {
    name: searchParams.get("name") ?? "",
    scope: searchParams.get("scope"),
    teamId: searchParams.get("team"),
    labels: parseLabelFilter(searchParams.get("labels")),
    status: searchParams.get("status") === "deleted" ? "deleted" : "active",
  };
  const sortBy = (searchParams.get("sortBy") as SortBy | null) ?? "createdAt";
  const sortDirection = (searchParams.get("sortDirection") as SortDirection | null) ?? "desc";
  const page = Math.max(0, Number(searchParams.get("page") ?? 0) || 0);

  const update = useCallback(
    (
      patch: Partial<AgentFilters> & {
        sortBy?: SortBy;
        sortDirection?: SortDirection;
        page?: number;
      },
    ) => {
      const next = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string | null | undefined) => {
        if (value) next.set(key, value);
        else next.delete(key);
      };
      if ("name" in patch) set("name", patch.name);
      if ("scope" in patch) set("scope", patch.scope);
      if ("teamId" in patch) set("team", patch.teamId);
      if ("labels" in patch) set("labels", serializeLabelFilter(patch.labels ?? {}));
      if ("status" in patch) set("status", patch.status === "deleted" ? "deleted" : null);
      if (patch.sortBy) set("sortBy", patch.sortBy);
      if (patch.sortDirection) set("sortDirection", patch.sortDirection);
      if ("page" in patch) set("page", patch.page ? String(patch.page) : null);
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  return { filters, sortBy, sortDirection, page, update };
}
