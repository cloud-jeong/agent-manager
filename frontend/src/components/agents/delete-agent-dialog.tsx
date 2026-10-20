"use client";

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
import type { Agent } from "@/lib/api/client";

/** Confirms a soft delete (restorable) or a permanent delete. */
export function DeleteAgentDialog({
  agent,
  permanent = false,
  pending,
  onConfirm,
  onOpenChange,
}: {
  agent: Agent | null;
  permanent?: boolean;
  pending: boolean;
  onConfirm: (agent: Agent) => void;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <AlertDialog open={agent !== null} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {permanent ? "Permanently delete" : "Delete"} “{agent?.name}”?
          </AlertDialogTitle>
          <AlertDialogDescription>
            {permanent
              ? "The agent, its team assignments, shares and labels are removed for good. This cannot be undone."
              : "The agent moves to Deleted agents. You can restore it from there later."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={pending}
            onClick={() => agent && onConfirm(agent)}
          >
            {permanent ? "Delete permanently" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
