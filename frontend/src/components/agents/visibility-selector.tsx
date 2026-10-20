"use client";

import { Building2, Lock, UsersRound, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AgentScope, Me, Team, User } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export type UserShare = { userId: string; level: "use" | "write" };

/**
 * Personal / Teams / Organization picker, mirroring Archestra's AccessLevelSelector.
 * The server re-validates every rule shown here.
 */
export function VisibilitySelector({
  me,
  scope,
  onScopeChange,
  teamIds,
  onTeamIdsChange,
  shares,
  onSharesChange,
  allTeams,
  allUsers,
  originalScope,
  authorId,
}: {
  me: Me;
  scope: AgentScope;
  onScopeChange: (scope: AgentScope) => void;
  teamIds: string[];
  onTeamIdsChange: (teamIds: string[]) => void;
  shares: UserShare[];
  onSharesChange: (shares: UserShare[]) => void;
  allTeams: Team[];
  allUsers: User[];
  /** Scope of the saved agent; shared agents cannot become personal again. */
  originalScope?: AgentScope;
  authorId?: string | null;
}) {
  const isAdmin = me.role === "admin";
  const adminTeamIds = new Set(me.teams.filter((t) => t.role === "team_admin").map((t) => t.id));
  const canChooseTeam = isAdmin || adminTeamIds.size > 0;

  const options: {
    value: AgentScope;
    label: string;
    description: string;
    icon: typeof Lock;
    disabledReason?: string;
  }[] = [
    {
      value: "personal",
      label: "Personal",
      description: "Only you and people you share it with",
      icon: Lock,
      disabledReason:
        originalScope && originalScope !== "personal"
          ? "Shared agents cannot be made personal again"
          : undefined,
    },
    {
      value: "team",
      label: "Teams",
      description: "Members of the selected teams",
      icon: UsersRound,
      disabledReason: canChooseTeam ? undefined : "You are not a team admin of any team",
    },
    {
      value: "org",
      label: "Organization",
      description: "Everyone in the organization",
      icon: Building2,
      disabledReason: isAdmin ? undefined : "Only admins can share with the whole organization",
    },
  ];

  const ownerId = authorId ?? me.id;
  const shareableUsers = allUsers.filter(
    (u) => u.id !== ownerId && !shares.some((s) => s.userId === u.id),
  );

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map((option) => {
          const disabled = Boolean(option.disabledReason) && scope !== option.value;
          return (
            <button
              key={option.value}
              type="button"
              disabled={disabled}
              title={option.disabledReason}
              onClick={() => onScopeChange(option.value)}
              className={cn(
                "flex flex-col items-start gap-1 rounded-lg border p-3 text-left text-sm transition-colors",
                scope === option.value ? "border-primary ring-1 ring-primary" : "hover:bg-muted",
                disabled && "cursor-not-allowed opacity-50 hover:bg-transparent",
              )}
            >
              <span className="flex items-center gap-1.5 font-medium">
                <option.icon className="size-4" />
                {option.label}
              </span>
              <span className="text-xs text-muted-foreground">{option.description}</span>
            </button>
          );
        })}
      </div>

      {scope === "team" && (
        <div className="space-y-2 rounded-lg border p-3">
          <Label>Teams</Label>
          {allTeams.length === 0 && (
            <p className="text-sm text-muted-foreground">No teams exist yet.</p>
          )}
          {allTeams.map((team) => {
            const checked = teamIds.includes(team.id);
            const editable = isAdmin || adminTeamIds.has(team.id);
            return (
              <label
                key={team.id}
                className={cn(
                  "flex items-center gap-2 text-sm",
                  !editable && "text-muted-foreground",
                )}
              >
                <Checkbox
                  checked={checked}
                  disabled={!editable}
                  onCheckedChange={(next) =>
                    onTeamIdsChange(
                      next ? [...teamIds, team.id] : teamIds.filter((id) => id !== team.id),
                    )
                  }
                />
                {team.name}
                {!editable && <span className="text-xs">(you are not a team admin)</span>}
              </label>
            );
          })}
        </div>
      )}

      {scope === "personal" && (
        <div className="space-y-2 rounded-lg border p-3">
          <Label>Share with people</Label>
          {shares.map((share) => {
            const user = allUsers.find((u) => u.id === share.userId);
            return (
              <div key={share.userId} className="flex items-center gap-2 text-sm">
                <span className="flex-1">
                  {user?.name ?? share.userId}{" "}
                  <span className="text-muted-foreground">{user?.email}</span>
                </span>
                <Select
                  value={share.level}
                  onValueChange={(level) =>
                    onSharesChange(
                      shares.map((s) =>
                        s.userId === share.userId ? { ...s, level: level as UserShare["level"] } : s,
                      ),
                    )
                  }
                  items={SHARE_LEVELS}
                >
                  <SelectTrigger size="sm" className="w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SHARE_LEVELS.map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove"
                  onClick={() => onSharesChange(shares.filter((s) => s.userId !== share.userId))}
                >
                  <X className="size-4" />
                </Button>
              </div>
            );
          })}
          {shareableUsers.length > 0 && (
            <Select
              value={null}
              onValueChange={(userId) =>
                userId && onSharesChange([...shares, { userId: userId as string, level: "use" }])
              }
              items={shareableUsers.map((u) => ({ value: u.id, label: u.name }))}
            >
              <SelectTrigger size="sm" className="w-56">
                <SelectValue placeholder="Add a person…" />
              </SelectTrigger>
              <SelectContent>
                {shareableUsers.map((u) => (
                  <SelectItem key={u.id} value={u.id}>
                    {u.name} <span className="text-muted-foreground">{u.email}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      )}
    </div>
  );
}

const SHARE_LEVELS = [
  { value: "use", label: "Can use" },
  { value: "write", label: "Can edit" },
];
