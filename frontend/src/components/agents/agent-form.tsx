"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { LabelsEditor } from "@/components/agents/labels-editor";
import { VisibilitySelector } from "@/components/agents/visibility-selector";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { Agent, AgentCreate, Me } from "@/lib/api/client";
import { useTeams, useUsers } from "@/lib/queries/teams";

const formSchema = z
  .object({
    name: z.string().trim().min(1, "Name is required").max(200),
    icon: z.string().max(32),
    description: z.string(),
    systemPrompt: z.string(),
    agentType: z.enum(["agent", "mcp_gateway"]),
    considerContextUntrusted: z.boolean(),
    scope: z.enum(["personal", "team", "org"]),
    teams: z.array(z.string()),
    users: z.array(z.object({ userId: z.string(), level: z.enum(["use", "write"]) })),
    labels: z.array(z.object({ key: z.string(), value: z.string() })),
  })
  .superRefine((values, ctx) => {
    if (values.scope === "team" && values.teams.length === 0) {
      ctx.addIssue({ code: "custom", path: ["teams"], message: "Select at least one team" });
    }
    const keys = values.labels.map((l) => l.key.trim()).filter(Boolean);
    if (new Set(keys).size !== keys.length) {
      ctx.addIssue({ code: "custom", path: ["labels"], message: "Label keys must be unique" });
    }
    if (values.labels.some((l) => !l.key.trim() !== !l.value.trim())) {
      ctx.addIssue({
        code: "custom",
        path: ["labels"],
        message: "Every label needs both a key and a value",
      });
    }
  });

type FormValues = z.infer<typeof formSchema>;

export function AgentForm({
  me,
  agent,
  submitLabel,
  submitting,
  onSubmit,
  onCancel,
}: {
  me: Me;
  agent?: Agent;
  submitLabel: string;
  submitting: boolean;
  /** Receives a full payload; it is valid both for create and for update. */
  onSubmit: (payload: AgentCreate) => void;
  onCancel: () => void;
}) {
  const teams = useTeams();
  const users = useUsers();
  const readOnly = agent !== undefined && !agent.canModify;

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: agent?.name ?? "",
      icon: agent?.icon ?? "",
      description: agent?.description ?? "",
      systemPrompt: agent?.systemPrompt ?? "",
      agentType: agent?.agentType ?? "agent",
      considerContextUntrusted: agent?.considerContextUntrusted ?? false,
      scope: agent?.scope ?? "personal",
      teams: agent?.teams.map((t) => t.id) ?? [],
      users: agent?.users.map((u) => ({ userId: u.id, level: u.level })) ?? [],
      labels: agent?.labels ?? [],
    },
  });
  const { errors } = form.formState;
  const teamIds = useWatch({ control: form.control, name: "teams" });
  const shares = useWatch({ control: form.control, name: "users" });

  return (
    <form
      className="space-y-6"
      onSubmit={form.handleSubmit((values) =>
        onSubmit({
          name: values.name,
          icon: values.icon.trim() || null,
          description: values.description.trim() || null,
          systemPrompt: values.systemPrompt.trim() || null,
          agentType: values.agentType,
          considerContextUntrusted: values.considerContextUntrusted,
          scope: values.scope,
          teams: values.scope === "team" ? values.teams : [],
          users: values.scope === "personal" ? values.users : [],
          labels: values.labels
            .map((l) => ({ key: l.key.trim(), value: l.value.trim() }))
            .filter((l) => l.key && l.value),
        }),
      )}
    >
      <fieldset disabled={readOnly} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-[6rem_1fr]">
              <div className="space-y-2">
                <Label htmlFor="icon">Icon</Label>
                <Input id="icon" placeholder="🤖" {...form.register("icon")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">Name *</Label>
                <Input id="name" aria-invalid={!!errors.name} {...form.register("name")} />
                {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="agentType">Type</Label>
              <Controller
                control={form.control}
                name="agentType"
                render={({ field }) => (
                  <Select
                    value={field.value}
                    onValueChange={(v) => v && field.onChange(v)}
                    items={AGENT_TYPES}
                    disabled={readOnly}
                  >
                    <SelectTrigger id="agentType" className="w-56">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {AGENT_TYPES.map((t) => (
                        <SelectItem key={t.value} value={t.value}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Textarea id="description" rows={2} {...form.register("description")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="systemPrompt">Instructions (system prompt)</Label>
              <Textarea id="systemPrompt" rows={6} {...form.register("systemPrompt")} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Visibility</CardTitle>
            <CardDescription>Who can see and use this agent.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Controller
              control={form.control}
              name="scope"
              render={({ field }) => (
                <VisibilitySelector
                  me={me}
                  scope={field.value}
                  onScopeChange={field.onChange}
                  teamIds={teamIds}
                  onTeamIdsChange={(ids) => form.setValue("teams", ids, { shouldValidate: true })}
                  shares={shares}
                  onSharesChange={(shares) => form.setValue("users", shares)}
                  allTeams={teams.data ?? []}
                  allUsers={users.data ?? []}
                  originalScope={agent?.scope}
                  authorId={agent?.authorId}
                />
              )}
            />
            {errors.teams && <p className="text-sm text-destructive">{errors.teams.message}</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Labels</CardTitle>
            <CardDescription>Key/value pairs for organizing and filtering agents.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Controller
              control={form.control}
              name="labels"
              render={({ field }) => <LabelsEditor value={field.value} onChange={field.onChange} />}
            />
            {errors.labels && (
              <p className="text-sm text-destructive">{errors.labels.message}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Security</CardTitle>
          </CardHeader>
          <CardContent>
            <Controller
              control={form.control}
              name="considerContextUntrusted"
              render={({ field }) => (
                <label className="flex items-start gap-3 text-sm">
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    disabled={readOnly}
                  />
                  <span>
                    <span className="font-medium">Treat context as untrusted</span>
                    <span className="block text-muted-foreground">
                      Consider all context passed to this agent as untrusted data.
                    </span>
                  </span>
                </label>
              )}
            />
          </CardContent>
        </Card>
      </fieldset>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {readOnly ? "Back" : "Cancel"}
        </Button>
        {!readOnly && (
          <Button type="submit" disabled={submitting}>
            {submitting ? "Saving…" : submitLabel}
          </Button>
        )}
      </div>
    </form>
  );
}

const AGENT_TYPES = [
  { value: "agent", label: "Agent" },
  { value: "mcp_gateway", label: "MCP Gateway" },
];
