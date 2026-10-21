"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { LabelsEditor } from "@/components/agents/labels-editor";
import { VisibilitySelector } from "@/components/agents/visibility-selector";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useMcpServers } from "@/lib/queries/mcp-servers";
import { useTeams, useUsers } from "@/lib/queries/teams";

const formSchema = z
  .object({
    name: z.string().trim().min(1, "Name is required").max(200),
    icon: z.string().max(32),
    description: z.string(),
    systemPrompt: z.string(),
    agentType: z.enum(["agent", "mcp_gateway"]),
    considerContextUntrusted: z.boolean(),
    model: z.enum(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]),
    effort: z.enum(["low", "medium", "high", "xhigh", "max"]),
    maxTurns: z.number().int().min(1, "At least 1").max(200, "At most 200"),
    tools: z.object({
      bash: z.boolean(),
      textEditor: z.boolean(),
      webSearch: z.boolean(),
      webFetch: z.boolean(),
    }),
    sandboxNetwork: z.boolean(),
    mcpServers: z.array(z.string()),
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
  const mcpServers = useMcpServers();
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
      model: (agent?.model as FormValues["model"] | undefined) ?? "claude-opus-5-5",
      effort: agent?.effort ?? "medium",
      maxTurns: agent?.maxTurns ?? 30,
      tools: {
        bash: agent?.tools.bash ?? false,
        textEditor: agent?.tools.textEditor ?? false,
        webSearch: agent?.tools.webSearch ?? false,
        webFetch: agent?.tools.webFetch ?? false,
      },
      sandboxNetwork: agent?.sandboxNetwork ?? false,
      mcpServers: agent?.mcpServers.map((m) => m.id) ?? [],
      scope: agent?.scope ?? "personal",
      teams: agent?.teams.map((t) => t.id) ?? [],
      users: agent?.users.map((u) => ({ userId: u.id, level: u.level })) ?? [],
      labels: agent?.labels ?? [],
    },
  });
  const { errors } = form.formState;
  const teamIds = useWatch({ control: form.control, name: "teams" });
  const shares = useWatch({ control: form.control, name: "users" });
  const agentType = useWatch({ control: form.control, name: "agentType" });
  const tools = useWatch({ control: form.control, name: "tools" });
  const usesSandbox = tools.bash || tools.textEditor;

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
          model: values.model,
          effort: values.effort,
          maxTurns: values.maxTurns,
          tools: values.tools,
          sandboxNetwork: values.sandboxNetwork,
          mcpServers: values.mcpServers,
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

        {agentType === "agent" && (
          <Card>
            <CardHeader>
              <CardTitle>Runtime</CardTitle>
              <CardDescription>Model and tools used when this agent runs.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="model">Model</Label>
                  <Controller
                    control={form.control}
                    name="model"
                    render={({ field }) => (
                      <Select
                        value={field.value}
                        onValueChange={(v) => v && field.onChange(v)}
                        items={MODELS}
                        disabled={readOnly}
                      >
                        <SelectTrigger id="model" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {MODELS.map((m) => (
                            <SelectItem key={m.value} value={m.value}>
                              {m.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="effort">Effort</Label>
                  <Controller
                    control={form.control}
                    name="effort"
                    render={({ field }) => (
                      <Select
                        value={field.value}
                        onValueChange={(v) => v && field.onChange(v)}
                        items={EFFORTS}
                        disabled={readOnly}
                      >
                        <SelectTrigger id="effort" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {EFFORTS.map((e) => (
                            <SelectItem key={e.value} value={e.value}>
                              {e.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="maxTurns">Max turns per run</Label>
                  <Input
                    id="maxTurns"
                    type="number"
                    min={1}
                    max={200}
                    aria-invalid={!!errors.maxTurns}
                    {...form.register("maxTurns", { valueAsNumber: true })}
                  />
                  {errors.maxTurns && (
                    <p className="text-sm text-destructive">{errors.maxTurns.message}</p>
                  )}
                </div>
              </div>
              <div className="space-y-3">
                <Label>Tools</Label>
                {TOOLS.map((tool) => (
                  <Controller
                    key={tool.name}
                    control={form.control}
                    name={`tools.${tool.name}`}
                    render={({ field }) => (
                      <label className="flex items-start gap-3 text-sm">
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={readOnly}
                        />
                        <span>
                          <span className="font-medium">{tool.label}</span>
                          <span className="block text-muted-foreground">{tool.description}</span>
                        </span>
                      </label>
                    )}
                  />
                ))}
              </div>
              {(mcpServers.data?.length ?? 0) > 0 && (
                <div className="space-y-3">
                  <Label>MCP servers</Label>
                  <Controller
                    control={form.control}
                    name="mcpServers"
                    render={({ field }) => (
                      <div className="space-y-2">
                        {mcpServers.data?.map((server) => (
                          <label key={server.id} className="flex items-start gap-3 text-sm">
                            <Checkbox
                              checked={field.value.includes(server.id)}
                              disabled={readOnly}
                              onCheckedChange={(checked) =>
                                field.onChange(
                                  checked
                                    ? [...field.value, server.id]
                                    : field.value.filter((id) => id !== server.id),
                                )
                              }
                            />
                            <span>
                              <span className="font-medium">{server.name}</span>
                              <span className="block text-muted-foreground">
                                {server.description ?? server.url}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    )}
                  />
                </div>
              )}
              {usesSandbox && (
                <Controller
                  control={form.control}
                  name="sandboxNetwork"
                  render={({ field }) => (
                    <label className="flex items-start gap-3 text-sm">
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={readOnly}
                      />
                      <span>
                        <span className="font-medium">Sandbox network access</span>
                        <span className="block text-muted-foreground">
                          Let commands in the sandbox reach the network (off by default).
                        </span>
                      </span>
                    </label>
                  )}
                />
              )}
            </CardContent>
          </Card>
        )}

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

const MODELS = [
  { value: "claude-opus-5-5", label: "Claude Opus 5.5" },
  { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
  { value: "claude-haiku-5-5", label: "Claude Haiku 5.5" },
  { value: "claude-fable-5-1", label: "Claude Fable 5.1" },
];

const EFFORTS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra high" },
  { value: "max", label: "Max" },
];

const TOOLS = [
  {
    name: "bash",
    label: "Bash",
    description: "Run shell commands in an isolated sandbox container.",
  },
  {
    name: "textEditor",
    label: "File editor",
    description: "View, create and edit files in the sandbox workspace.",
  },
  { name: "webSearch", label: "Web search", description: "Search the web (runs on Anthropic)." },
  {
    name: "webFetch",
    label: "Web fetch",
    description: "Fetch pages whose URLs appear in the conversation (runs on Anthropic).",
  },
] as const;

const AGENT_TYPES = [
  { value: "agent", label: "Agent" },
  { value: "mcp_gateway", label: "MCP Gateway" },
];
