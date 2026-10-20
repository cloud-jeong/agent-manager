"use client";

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Building2,
  Lock,
  MoreHorizontal,
  Star,
  UsersRound,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Agent } from "@/lib/api/client";

export type SortBy = "name" | "createdAt" | "team";
export type SortDirection = "asc" | "desc";

export function AgentsTable({
  agents,
  deletedView,
  defaultAgentId,
  sortBy,
  sortDirection,
  onSort,
  onDelete,
  onRestore,
  onPurge,
  onToggleDefault,
}: {
  agents: Agent[];
  deletedView: boolean;
  defaultAgentId: string | null;
  sortBy: SortBy;
  sortDirection: SortDirection;
  onSort: (sortBy: SortBy) => void;
  onDelete: (agent: Agent) => void;
  onRestore: (agent: Agent) => void;
  onPurge: (agent: Agent) => void;
  onToggleDefault: (agent: Agent) => void;
}) {
  const sortHeader = (column: SortBy, label: string) => {
    const Icon =
      sortBy !== column ? ArrowUpDown : sortDirection === "asc" ? ArrowUp : ArrowDown;
    return (
      <button
        type="button"
        className="flex items-center gap-1 hover:text-foreground"
        onClick={() => onSort(column)}
      >
        {label}
        <Icon className="size-3.5" />
      </button>
    );
  };

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{sortHeader("name", "Name")}</TableHead>
            <TableHead>{sortHeader("team", "Accessible to")}</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Author</TableHead>
            <TableHead>{sortHeader("createdAt", "Created")}</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {agents.map((agent) => {
            const isDefault = agent.id === defaultAgentId;
            return (
              <TableRow key={agent.id}>
                <TableCell className="max-w-sm">
                  <div className="flex items-start gap-2">
                    <span className="w-6 text-lg leading-6">{agent.icon || "🤖"}</span>
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        {deletedView ? (
                          <span className="font-medium">{agent.name}</span>
                        ) : (
                          <Link href={`/agents/${agent.id}`} className="font-medium hover:underline">
                            {agent.name}
                          </Link>
                        )}
                        {isDefault && (
                          <Badge variant="outline" className="gap-1">
                            <Star className="size-3" /> Default
                          </Badge>
                        )}
                      </div>
                      {agent.description && (
                        <p className="truncate text-xs text-muted-foreground">
                          {agent.description}
                        </p>
                      )}
                      {agent.labels.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {agent.labels.map((l) => (
                            <Badge key={l.key} variant="secondary" className="font-normal">
                              {l.key}: {l.value}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <AccessibleTo agent={agent} />
                </TableCell>
                <TableCell className="text-sm">
                  {agent.agentType === "mcp_gateway" ? "MCP Gateway" : "Agent"}
                </TableCell>
                <TableCell className="text-sm">{agent.authorName ?? "—"}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(agent.createdAt).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={<Button variant="ghost" size="icon-sm" aria-label="Actions" />}
                    >
                      <MoreHorizontal className="size-4" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {deletedView ? (
                        <>
                          <DropdownMenuItem onClick={() => onRestore(agent)}>Restore</DropdownMenuItem>
                          <DropdownMenuItem variant="destructive" onClick={() => onPurge(agent)}>
                            Delete permanently
                          </DropdownMenuItem>
                        </>
                      ) : (
                        <>
                          <DropdownMenuItem render={<Link href={`/agents/${agent.id}`} />}>
                            {agent.canModify ? "Edit" : "View"}
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => onToggleDefault(agent)}>
                            {isDefault ? "Unset as default" : "Set as my default"}
                          </DropdownMenuItem>
                          {agent.canModify && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant="destructive"
                                onClick={() => onDelete(agent)}
                              >
                                Delete
                              </DropdownMenuItem>
                            </>
                          )}
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function AccessibleTo({ agent }: { agent: Agent }) {
  if (agent.scope === "org") {
    return (
      <span className="flex items-center gap-1.5 text-sm">
        <Building2 className="size-4 text-muted-foreground" /> Organization
      </span>
    );
  }
  if (agent.scope === "team") {
    return (
      <span className="flex flex-wrap items-center gap-1.5 text-sm">
        <UsersRound className="size-4 text-muted-foreground" />
        {agent.teams.length ? agent.teams.map((t) => t.name).join(", ") : "No teams"}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-sm">
      <Lock className="size-4 text-muted-foreground" />
      Personal
      {agent.users.length > 0 && (
        <span className="text-muted-foreground">+{agent.users.length} shared</span>
      )}
    </span>
  );
}
