"use client";

import { Plus, X } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLabelKeys, useLabelValues } from "@/lib/queries/agents";

export type LabelPair = { key: string; value: string };

/** Key/value label rows with autocomplete from existing labels (one value per key). */
export function LabelsEditor({
  value,
  onChange,
}: {
  value: LabelPair[];
  onChange: (labels: LabelPair[]) => void;
}) {
  const listId = useId();
  const keys = useLabelKeys();
  const duplicateKeys = findDuplicates(value.map((l) => l.key.trim()).filter(Boolean));

  return (
    <div className="space-y-2">
      <datalist id={`${listId}-keys`}>
        {keys.data?.map((k) => (
          <option key={k} value={k} />
        ))}
      </datalist>
      {value.map((label, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            placeholder="key"
            list={`${listId}-keys`}
            value={label.key}
            aria-invalid={duplicateKeys.has(label.key.trim()) || undefined}
            onChange={(e) => onChange(replaceAt(value, index, { ...label, key: e.target.value }))}
          />
          <LabelValueInput
            labelKey={label.key.trim()}
            value={label.value}
            onChange={(v) => onChange(replaceAt(value, index, { ...label, value: v }))}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Remove label"
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          >
            <X className="size-4" />
          </Button>
        </div>
      ))}
      {duplicateKeys.size > 0 && (
        <p className="text-sm text-destructive">Each label key can only be used once.</p>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onChange([...value, { key: "", value: "" }])}
      >
        <Plus className="size-4" />
        Add label
      </Button>
    </div>
  );
}

function LabelValueInput({
  labelKey,
  value,
  onChange,
}: {
  labelKey: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const listId = useId();
  const values = useLabelValues(labelKey || undefined);
  return (
    <>
      <datalist id={listId}>
        {values.data?.map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>
      <Input
        placeholder="value"
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </>
  );
}

function replaceAt<T>(items: T[], index: number, item: T): T[] {
  return items.map((existing, i) => (i === index ? item : existing));
}

function findDuplicates(items: string[]): Set<string> {
  const seen = new Set<string>();
  const dupes = new Set<string>();
  for (const item of items) {
    if (seen.has(item)) dupes.add(item);
    seen.add(item);
  }
  return dupes;
}
