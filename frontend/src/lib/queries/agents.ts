import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type AgentCreate, type AgentUpdate, api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type AgentListParams = NonNullable<
  paths["/api/agents"]["get"]["parameters"]["query"]
>;

const agentKeys = {
  all: ["agents"] as const,
  list: (params: AgentListParams) => ["agents", "list", params] as const,
  visible: ["agents", "all"] as const,
  detail: (id: string) => ["agents", "detail", id] as const,
  labelKeys: ["agents", "labels", "keys"] as const,
  labelValues: (key?: string) => ["agents", "labels", "values", key ?? null] as const,
  defaultAgent: ["members", "default-agent"] as const,
};

export function useAgentsPaginated(params: AgentListParams) {
  return useQuery({
    queryKey: agentKeys.list(params),
    queryFn: () => unwrap(api.GET("/api/agents", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
}

export function useAllAgents() {
  return useQuery({
    queryKey: agentKeys.visible,
    queryFn: () => unwrap(api.GET("/api/agents/all")),
  });
}

export function useAgent(id: string) {
  return useQuery({
    queryKey: agentKeys.detail(id),
    queryFn: () => unwrap(api.GET("/api/agents/{agent_id}", { params: { path: { agent_id: id } } })),
    retry: false,
  });
}

export function useCreateAgent() {
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (body: AgentCreate) => unwrap(api.POST("/api/agents", { body })),
    onSuccess: invalidate,
  });
}

export function useUpdateAgent(id: string) {
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (body: AgentUpdate) =>
      unwrap(api.PUT("/api/agents/{agent_id}", { params: { path: { agent_id: id } }, body })),
    onSuccess: invalidate,
  });
}

export function useDeleteAgent() {
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/agents/{agent_id}", { params: { path: { agent_id: id } } })),
    onSuccess: invalidate,
  });
}

export function useRestoreAgent() {
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/agents/{agent_id}/restore", { params: { path: { agent_id: id } } }),
      ),
    onSuccess: invalidate,
  });
}

export function usePurgeAgent() {
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/agents/{agent_id}/permanent", { params: { path: { agent_id: id } } }),
      ),
    onSuccess: invalidate,
  });
}

export function useLabelKeys() {
  return useQuery({
    queryKey: agentKeys.labelKeys,
    queryFn: () => unwrap(api.GET("/api/agents/labels/keys")),
  });
}

export function useLabelValues(key?: string) {
  return useQuery({
    queryKey: agentKeys.labelValues(key),
    queryFn: () =>
      unwrap(api.GET("/api/agents/labels/values", { params: { query: key ? { key } : {} } })),
  });
}

export function useDefaultAgentId() {
  return useQuery({
    queryKey: agentKeys.defaultAgent,
    queryFn: async () =>
      (await unwrap(api.GET("/api/members/default-agent"))).defaultAgentId ?? null,
  });
}

export function useSetDefaultAgentId() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (defaultAgentId: string | null) =>
      unwrap(api.PUT("/api/members/default-agent", { body: { defaultAgentId } })),
    onSuccess: (data) => {
      queryClient.setQueryData(agentKeys.defaultAgent, data.defaultAgentId ?? null);
    },
  });
}

function useInvalidateAgents() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: agentKeys.all }),
      // Deleting an agent clears default-agent pins server-side.
      queryClient.invalidateQueries({ queryKey: agentKeys.defaultAgent }),
    ]);
}
