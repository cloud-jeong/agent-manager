"use client";

import { KeyRound, Trash2 } from "lucide-react";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { McpServer } from "@/lib/api/client";
import {
  useCreateMcpServer,
  useDeleteMcpServer,
  useMcpServers,
} from "@/lib/queries/mcp-servers";

export function McpServersSettingsPage() {
  return (
    <AppShell adminOnly>
      {() => (
        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-semibold">MCP servers</h1>
            <p className="text-sm text-muted-foreground">
              Remote MCP servers agents can use. Claude connects to them directly from
              Anthropic&apos;s servers, so they must be reachable over public HTTPS.
            </p>
          </div>
          <AddServerForm />
          <ServerList />
        </div>
      )}
    </AppShell>
  );
}

function AddServerForm() {
  const create = useCreateMcpServer();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [token, setToken] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add a server</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              {
                name: name.trim(),
                url: url.trim(),
                description: description.trim() || null,
                token: token || null,
              },
              {
                onSuccess: () => {
                  setName("");
                  setUrl("");
                  setDescription("");
                  setToken("");
                  toast.success("MCP server added");
                },
                onError: (err) => toast.error(err.message),
              },
            );
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="mcp-name">Name</Label>
            <Input
              id="mcp-name"
              placeholder="github"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Letters, digits, - and _ only.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="mcp-url">URL</Label>
            <Input
              id="mcp-url"
              placeholder="https://mcp.example.com/mcp"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mcp-description">Description</Label>
            <Input
              id="mcp-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mcp-token">Authorization token (optional)</Label>
            <Input
              id="mcp-token"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Stored encrypted and never shown again.
            </p>
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={!name.trim() || !url.trim() || create.isPending}>
              Add server
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function ServerList() {
  const servers = useMcpServers();
  const remove = useDeleteMcpServer();
  const [toDelete, setToDelete] = useState<McpServer | null>(null);

  if (servers.data?.length === 0) {
    return <p className="text-sm text-muted-foreground">No MCP servers registered yet.</p>;
  }
  return (
    <>
      <div className="divide-y rounded-md border">
        {servers.data?.map((server) => (
          <div key={server.id} className="flex items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{server.name}</span>
                {server.hasToken && (
                  <Badge variant="secondary" className="gap-1">
                    <KeyRound className="size-3" />
                    token
                  </Badge>
                )}
              </div>
              <div className="truncate font-mono text-xs text-muted-foreground">{server.url}</div>
              {server.description && (
                <div className="text-sm text-muted-foreground">{server.description}</div>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Delete ${server.name}`}
              onClick={() => setToDelete(server)}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        ))}
      </div>
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{toDelete?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Agents using this server lose access to its tools.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={remove.isPending}
              onClick={() =>
                toDelete &&
                remove.mutate(toDelete.id, {
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
    </>
  );
}
