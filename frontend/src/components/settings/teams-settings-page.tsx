"use client";

import { Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Team, User } from "@/lib/api/client";
import {
  useCreateTeam,
  useCreateUser,
  useDeleteTeam,
  useRemoveTeamMember,
  useTeams,
  useUpsertTeamMember,
  useUsers,
} from "@/lib/queries/teams";

type TeamRole = "member" | "team_admin";

export function TeamsSettingsPage() {
  return (
    <AppShell adminOnly>
      {() => (
        <div className="space-y-8">
          <TeamsSection />
          <UsersSection />
        </div>
      )}
    </AppShell>
  );
}

function TeamsSection() {
  const teams = useTeams();
  const users = useUsers();
  const createTeam = useCreateTeam();
  const deleteTeam = useDeleteTeam();
  const [name, setName] = useState("");
  const [toDelete, setToDelete] = useState<Team | null>(null);

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Teams</h1>
        <p className="text-sm text-muted-foreground">
          Team admins can create and manage team-scoped agents for their team.
        </p>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          createTeam.mutate(
            { name: name.trim() },
            {
              onSuccess: () => setName(""),
              onError: (err) => toast.error(err.message),
            },
          );
        }}
      >
        <Input
          className="w-64"
          placeholder="New team name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button type="submit" disabled={!name.trim() || createTeam.isPending}>
          Create team
        </Button>
      </form>
      <div className="grid gap-4 md:grid-cols-2">
        {teams.data?.map((team) => (
          <TeamCard
            key={team.id}
            team={team}
            users={users.data ?? []}
            onDelete={() => setToDelete(team)}
          />
        ))}
      </div>
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete team “{toDelete?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Agents shared only with this team will become visible to admins only.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteTeam.isPending}
              onClick={() =>
                toDelete &&
                deleteTeam.mutate(toDelete.id, {
                  onSuccess: () => setToDelete(null),
                  onError: (err) => toast.error(err.message),
                })
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function TeamCard({
  team,
  users,
  onDelete,
}: {
  team: Team;
  users: User[];
  onDelete: () => void;
}) {
  const upsert = useUpsertTeamMember();
  const remove = useRemoveTeamMember();
  const candidates = users.filter((u) => !team.members.some((m) => m.userId === u.id));
  const onError = (err: Error) => toast.error(err.message);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between">
        <div>
          <CardTitle>{team.name}</CardTitle>
          {team.description && <CardDescription>{team.description}</CardDescription>}
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Delete team" onClick={onDelete}>
          <Trash2 className="size-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-2">
        {team.members.length === 0 && (
          <p className="text-sm text-muted-foreground">No members yet.</p>
        )}
        {team.members.map((member) => (
          <div key={member.userId} className="flex items-center gap-2 text-sm">
            <span className="flex-1">
              {member.name} <span className="text-muted-foreground">{member.email}</span>
            </span>
            <Select
              value={member.role}
              items={TEAM_ROLES}
              onValueChange={(role) =>
                role &&
                upsert.mutate(
                  { teamId: team.id, userId: member.userId, role: role as TeamRole },
                  { onError },
                )
              }
            >
              <SelectTrigger size="sm" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TEAM_ROLES.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Remove member"
              onClick={() => remove.mutate({ teamId: team.id, userId: member.userId }, { onError })}
            >
              <X className="size-4" />
            </Button>
          </div>
        ))}
        {candidates.length > 0 && (
          <Select
            value={null}
            items={candidates.map((u) => ({ value: u.id, label: u.name }))}
            onValueChange={(userId) =>
              userId &&
              upsert.mutate(
                { teamId: team.id, userId: userId as string, role: "member" },
                { onError },
              )
            }
          >
            <SelectTrigger size="sm" className="w-56">
              <SelectValue placeholder="Add a member…" />
            </SelectTrigger>
            <SelectContent>
              {candidates.map((u) => (
                <SelectItem key={u.id} value={u.id}>
                  {u.name} <span className="text-muted-foreground">{u.email}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </CardContent>
    </Card>
  );
}

function UsersSection() {
  const users = useUsers();
  const createUser = useCreateUser();
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "member" });

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Users</h2>
        <p className="text-sm text-muted-foreground">Admins see and manage every agent.</p>
      </div>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          createUser.mutate(
            { ...form, role: form.role as "admin" | "member" },
            {
              onSuccess: () => {
                setForm({ name: "", email: "", password: "", role: "member" });
                toast.success("User created");
              },
              onError: (err) => toast.error(err.message),
            },
          );
        }}
      >
        <Input
          className="w-40"
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <Input
          className="w-56"
          type="email"
          placeholder="Email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          required
        />
        <Input
          className="w-44"
          type="password"
          placeholder="Password (8+ chars)"
          minLength={8}
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          required
        />
        <Select
          value={form.role}
          items={USER_ROLES}
          onValueChange={(role) => role && setForm({ ...form, role: role as string })}
        >
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {USER_ROLES.map((r) => (
              <SelectItem key={r.value} value={r.value}>
                {r.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button type="submit" disabled={createUser.isPending}>
          Add user
        </Button>
      </form>
      <div className="divide-y rounded-lg border">
        {users.data?.map((u) => (
          <div key={u.id} className="flex items-center gap-2 px-4 py-2 text-sm">
            <span className="flex-1">
              {u.name} <span className="text-muted-foreground">{u.email}</span>
            </span>
            {u.role === "admin" && <Badge>admin</Badge>}
          </div>
        ))}
      </div>
    </section>
  );
}

const TEAM_ROLES = [
  { value: "member", label: "Member" },
  { value: "team_admin", label: "Team admin" },
];

const USER_ROLES = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
];
