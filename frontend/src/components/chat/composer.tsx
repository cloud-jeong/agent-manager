"use client";

import { ArrowUp, Square } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/** Message input: Enter sends, Shift+Enter adds a line. Shows Stop while a run is active. */
export function Composer({
  onSend,
  onStop,
  running,
  disabled = false,
  placeholder = "Message the agent…",
}: {
  onSend: (content: string) => Promise<unknown> | void;
  onStop?: () => void;
  running: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const canSend = value.trim() !== "" && !running && !sending && !disabled;

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      await onSend(value.trim());
      setValue("");
    } catch {
      // The caller reports the error; keep the text so it can be retried.
    } finally {
      setSending(false);
    }
  };

  return (
    <form
      className="relative"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <Textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void send();
          }
        }}
        placeholder={placeholder}
        disabled={disabled}
        rows={3}
        className="max-h-60 resize-none pr-14"
      />
      <div className="absolute right-2 bottom-2">
        {running && onStop ? (
          <Button type="button" size="icon" variant="outline" onClick={onStop} aria-label="Stop">
            <Square className="size-4" />
          </Button>
        ) : (
          <Button type="submit" size="icon" disabled={!canSend} aria-label="Send">
            <ArrowUp className="size-4" />
          </Button>
        )}
      </div>
    </form>
  );
}
