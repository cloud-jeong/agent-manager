"use client";

import { MessageSquarePlus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/app-shell";
import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { useRunStream } from "@/components/chat/use-run-stream";
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
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { Conversation } from "@/lib/api/client";
import { useAllAgents, useDefaultAgentId } from "@/lib/queries/agents";
import {
  useCancelRun,
  useConversation,
  useConversations,
  useDeleteConversation,
  useSendMessage,
  useStartConversation,
} from "@/lib/queries/conversations";
import { cn } from "@/lib/utils";

export function NewChatPage() {
  return <AppShell>{() => <ChatLayout>{<NewConversation />}</ChatLayout>}</AppShell>;
}

export function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <AppShell>
      {() => (
        <ChatLayout activeId={id}>
          <ConversationView key={id} id={id} />
        </ChatLayout>
      )}
    </AppShell>
  );
}

function ChatLayout({ activeId, children }: { activeId?: string; children: React.ReactNode }) {
  return (
    <div className="grid h-[calc(100vh-6.5rem)] grid-cols-1 gap-4 md:grid-cols-[16rem_1fr]">
      <ConversationSidebar activeId={activeId} />
      <section className="flex min-h-0 flex-col">{children}</section>
    </div>
  );
}

// =============================================================================
// Sidebar
// =============================================================================

function ConversationSidebar({ activeId }: { activeId?: string }) {
  const router = useRouter();
  const conversations = useConversations();
  const remove = useDeleteConversation();
  const [deleting, setDeleting] = useState<Conversation | null>(null);

  return (
    <aside className="hidden min-h-0 flex-col gap-2 md:flex">
      <Button variant="outline" nativeButton={false} render={<Link href="/chat" />}>
        <MessageSquarePlus className="size-4" />
        New chat
      </Button>
      <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {conversations.isPending &&
          [0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
        {conversations.data?.data.length === 0 && (
          <p className="px-2 py-4 text-sm text-muted-foreground">No conversations yet.</p>
        )}
        {conversations.data?.data.map((c) => (
          <div
            key={c.id}
            className={cn(
              "group flex items-center rounded-md hover:bg-muted",
              c.id === activeId && "bg-muted",
            )}
          >
            <Link href={`/chat/${c.id}`} className="min-w-0 flex-1 px-2 py-1.5">
              <div className="truncate text-sm">{c.title}</div>
              <div className="truncate text-xs text-muted-foreground">
                {c.agent.icon ?? "🤖"} {c.agent.name}
              </div>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              className="mr-1 size-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
              aria-label={`Delete “${c.title}”`}
              onClick={() => setDeleting(c)}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
      </nav>

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{deleting?.title}”?</AlertDialogTitle>
            <AlertDialogDescription>
              The conversation, its run history and its sandbox files are removed. This cannot
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={remove.isPending}
              onClick={() =>
                deleting &&
                remove.mutate(deleting.id, {
                  onSuccess: () => {
                    if (deleting.id === activeId) router.push("/chat");
                    setDeleting(null);
                  },
                  onError: (e) => toast.error(e.message),
                })
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}

// =============================================================================
// New conversation
// =============================================================================

function NewConversation() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const agents = useAllAgents();
  const defaultAgentId = useDefaultAgentId();
  const start = useStartConversation();
  const [picked, setPicked] = useState<string | null>(null);

  const runnable = (agents.data ?? []).filter((a) => a.agentType === "agent");
  const preferred = [picked, searchParams.get("agentId"), defaultAgentId.data].find(
    (id) => id && runnable.some((a) => a.id === id),
  );
  const agentId = preferred ?? runnable[0]?.id ?? null;
  const agent = runnable.find((a) => a.id === agentId);
  const items = runnable.map((a) => ({ value: a.id, label: `${a.icon ?? "🤖"} ${a.name}` }));

  if (agents.isPending) return <Skeleton className="h-40 w-full" />;
  if (runnable.length === 0) {
    return (
      <div className="m-auto max-w-md text-center text-sm text-muted-foreground">
        There are no agents you can chat with yet.{" "}
        <Link href="/agents/new" className="underline">
          Create one
        </Link>
        .
      </div>
    );
  }

  return (
    <div className="m-auto w-full max-w-2xl space-y-4">
      <div className="space-y-1 text-center">
        <h1 className="text-2xl font-semibold">Start a conversation</h1>
        {agent?.description && (
          <p className="text-sm text-muted-foreground">{agent.description}</p>
        )}
      </div>
      <Select value={agentId} onValueChange={(v) => v && setPicked(v)} items={items}>
        <SelectTrigger className="mx-auto w-72" aria-label="Agent">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Composer
        running={false}
        disabled={!agentId || start.isPending}
        placeholder={agent ? `Message ${agent.name}…` : undefined}
        onSend={async (content) => {
          if (!agentId) return;
          await start.mutateAsync(
            { agentId, content },
            {
              onSuccess: ({ conversation }) => router.push(`/chat/${conversation.id}`),
              onError: (e) => toast.error(e.message),
            },
          );
        }}
      />
    </div>
  );
}

// =============================================================================
// Conversation
// =============================================================================

function ConversationView({ id }: { id: string }) {
  const conversation = useConversation(id);
  const send = useSendMessage(id);
  const cancel = useCancelRun();
  const activeRun = conversation.data?.activeRun ?? null;
  const live = useRunStream(id, activeRun?.id ?? null);
  const running = activeRun !== null;
  const bottomRef = useRef<HTMLDivElement>(null);

  // Keep the newest output in view.
  const messageCount = conversation.data?.messages.length ?? 0;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messageCount, live.text, live.thinking, running]);

  if (conversation.isPending) return <Skeleton className="h-full w-full" />;
  if (conversation.isError) {
    return (
      <p className="m-auto text-sm text-muted-foreground">
        This conversation does not exist or you don&apos;t have access to it.
      </p>
    );
  }

  const data = conversation.data;
  return (
    <>
      <header className="flex items-center gap-2 border-b pb-3">
        <span className="text-xl">{data.agent.icon ?? "🤖"}</span>
        <div className="min-w-0">
          <h1 className="truncate font-semibold">{data.title}</h1>
          <Link
            href={`/agents/${data.agent.id}`}
            className="text-xs text-muted-foreground hover:underline"
          >
            {data.agent.name}
          </Link>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto py-4 pr-2">
        <MessageList messages={data.messages} live={live} running={running} />
        <div ref={bottomRef} />
      </div>
      <Composer
        running={running}
        onStop={() =>
          activeRun &&
          cancel.mutate(activeRun.id, { onError: (e) => toast.error(e.message) })
        }
        onSend={(content) =>
          send.mutateAsync(content, { onError: (e) => toast.error(e.message) })
        }
      />
    </>
  );
}
