"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { AgentForm } from "@/components/agents/agent-form";
import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Me } from "@/lib/api/client";
import { useAgent, useCreateAgent, useUpdateAgent } from "@/lib/queries/agents";

export function AgentCreatePage() {
  return <AppShell>{(me) => <CreateAgent me={me} />}</AppShell>;
}

export function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <AppShell>{(me) => <EditAgent me={me} id={id} />}</AppShell>;
}

function CreateAgent({ me }: { me: Me }) {
  const router = useRouter();
  const create = useCreateAgent();
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="New agent" />
      <AgentForm
        me={me}
        submitLabel="Create agent"
        submitting={create.isPending}
        onCancel={() => router.push("/agents")}
        onSubmit={(payload) =>
          create.mutate(payload, {
            onSuccess: (agent) => {
              toast.success(`Created “${agent.name}”`);
              router.push(`/agents/${agent.id}`);
            },
            onError: (e) => toast.error(e.message),
          })
        }
      />
    </div>
  );
}

function EditAgent({ me, id }: { me: Me; id: string }) {
  const router = useRouter();
  const agent = useAgent(id);
  const update = useUpdateAgent(id);

  if (agent.isPending) return <Skeleton className="mx-auto h-96 max-w-3xl" />;
  if (agent.isError) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <PageHeader title="Agent not found" />
        <p className="text-sm text-muted-foreground">
          It may have been deleted, or you don&apos;t have access to it.
        </p>
      </div>
    );
  }

  const data = agent.data;
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title={`${data.icon ?? "🤖"} ${data.name}`}
        badge={
          data.deletedAt ? "Deleted" : !data.canModify ? "Read-only" : undefined
        }
        subtitle={`Created by ${data.authorName ?? "unknown"} on ${new Date(data.createdAt).toLocaleString()}`}
      />
      <AgentForm
        // Remount with fresh defaults after each save.
        key={data.updatedAt}
        me={me}
        agent={data.deletedAt ? { ...data, canModify: false } : data}
        submitLabel="Save changes"
        submitting={update.isPending}
        onCancel={() => router.push("/agents")}
        onSubmit={(payload) =>
          update.mutate(payload, {
            onSuccess: () => toast.success("Saved"),
            onError: (e) => toast.error(e.message),
          })
        }
      />
    </div>
  );
}

function PageHeader({
  title,
  subtitle,
  badge,
}: {
  title: string;
  subtitle?: string;
  badge?: string;
}) {
  return (
    <div className="space-y-1">
      <Link
        href="/agents"
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Agents
      </Link>
      <h1 className="flex items-center gap-2 text-2xl font-semibold">
        {title}
        {badge && <Badge variant="secondary">{badge}</Badge>}
      </h1>
      {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
    </div>
  );
}
