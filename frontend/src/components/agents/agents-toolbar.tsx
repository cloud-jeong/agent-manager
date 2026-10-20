"use client";

import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Team } from "@/lib/api/client";
import { useLabelKeys, useLabelValues } from "@/lib/queries/agents";
import { cn } from "@/lib/utils";

export type LabelFilter = Record<string, string[]>;

export type AgentFilters = {
  name: string;
  scope: string | null;
  teamId: string | null;
  labels: LabelFilter;
  status: "active" | "deleted";
};

export function AgentsToolbar({
  filters,
  onChange,
  teams,
}: {
  filters: AgentFilters;
  onChange: (patch: Partial<AgentFilters>) => void;
  teams: Team[];
}) {
  const [search, setSearch] = useState(filters.name);

  // Debounce the search box into the URL.
  useEffect(() => {
    if (search === filters.name) return;
    const timer = setTimeout(() => onChange({ name: search }), 300);
    return () => clearTimeout(timer);
  }, [search, filters.name, onChange]);

  const scopeItems = [{ value: ALL, label: "All visibility" }, ...SCOPES];
  const teamItems = [
    { value: ALL, label: "All teams" },
    ...teams.map((t) => ({ value: t.id, label: t.name })),
  ];
  const labelEntries = Object.entries(filters.labels);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-64">
          <Search className="absolute top-2 left-2.5 size-4 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Search by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select
          value={filters.scope ?? ALL}
          onValueChange={(v) => onChange({ scope: v === ALL ? null : (v as string) })}
          items={scopeItems}
        >
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {scopeItems.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={filters.teamId ?? ALL}
          onValueChange={(v) => onChange({ teamId: v === ALL ? null : (v as string) })}
          items={teamItems}
        >
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {teamItems.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <LabelFilterPicker
          onAdd={(key, value) => {
            const existing = filters.labels[key] ?? [];
            if (existing.includes(value)) return;
            onChange({ labels: { ...filters.labels, [key]: [...existing, value] } });
          }}
        />
        <div className="ml-auto flex rounded-lg border p-0.5">
          {(["active", "deleted"] as const).map((status) => (
            <button
              key={status}
              type="button"
              onClick={() => onChange({ status })}
              className={cn(
                "rounded-md px-3 py-1 text-sm capitalize",
                filters.status === status
                  ? "bg-muted font-medium"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {status}
            </button>
          ))}
        </div>
      </div>
      {labelEntries.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Labels:</span>
          {labelEntries.map(([key, values]) => (
            <Badge key={key} variant="secondary" className="gap-1">
              {key}: {values.join(" | ")}
              <button
                type="button"
                aria-label={`Remove ${key} filter`}
                onClick={() =>
                  onChange({
                    labels: Object.fromEntries(labelEntries.filter(([k]) => k !== key)),
                  })
                }
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
          <Button variant="link" size="sm" onClick={() => onChange({ labels: {} })}>
            Clear
          </Button>
        </div>
      )}
    </div>
  );
}

function LabelFilterPicker({ onAdd }: { onAdd: (key: string, value: string) => void }) {
  const keys = useLabelKeys();
  const [key, setKey] = useState<string | null>(null);
  const values = useLabelValues(key ?? undefined);

  if (!keys.data?.length) return null;
  return (
    <div className="flex items-center gap-1">
      <Select value={key} onValueChange={(v) => setKey(v as string | null)}>
        <SelectTrigger className="w-32">
          <SelectValue placeholder="Label key" />
        </SelectTrigger>
        <SelectContent>
          {keys.data.map((k) => (
            <SelectItem key={k} value={k}>
              {k}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={null}
        disabled={!key}
        onValueChange={(v) => {
          if (key && v) onAdd(key, v as string);
          setKey(null);
        }}
      >
        <SelectTrigger className="w-32">
          <SelectValue placeholder="Value" />
        </SelectTrigger>
        <SelectContent>
          {(key ? (values.data ?? []) : []).map((v) => (
            <SelectItem key={v} value={v}>
              {v}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

const ALL = "__all__";

export const SCOPES = [
  { value: "personal", label: "Personal" },
  { value: "team", label: "Teams" },
  { value: "org", label: "Organization" },
];

/** `{env: [prod, dev]}` <-> `env:prod|dev;owner:a` (the API's label filter format). */
export function serializeLabelFilter(labels: LabelFilter): string {
  return Object.entries(labels)
    .filter(([, values]) => values.length > 0)
    .map(([key, values]) => `${key}:${values.join("|")}`)
    .join(";");
}

export function parseLabelFilter(raw: string | null): LabelFilter {
  const result: LabelFilter = {};
  if (!raw) return result;
  for (const part of raw.split(";")) {
    const idx = part.indexOf(":");
    if (idx <= 0) continue;
    const values = part
      .slice(idx + 1)
      .split("|")
      .filter(Boolean);
    if (values.length) result[part.slice(0, idx)] = values;
  }
  return result;
}
