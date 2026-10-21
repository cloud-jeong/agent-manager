import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type RunListParams = NonNullable<paths["/api/runs"]["get"]["parameters"]["query"]>;

export const conversationKeys = {
  all: ["conversations"] as const,
  list: ["conversations", "list"] as const,
  detail: (id: string) => ["conversations", "detail", id] as const,
};

export const runKeys = {
  all: ["runs"] as const,
  list: (params: RunListParams) => ["runs", "list", params] as const,
};

export function useConversations() {
  return useQuery({
    queryKey: conversationKeys.list,
    queryFn: () => unwrap(api.GET("/api/conversations", { params: { query: { limit: 100 } } })),
  });
}

export function useConversation(id: string) {
  return useQuery({
    queryKey: conversationKeys.detail(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    retry: false,
  });
}

/** Creates a conversation and sends its first message in one step. */
export function useStartConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ agentId, content }: { agentId: string; content: string }) => {
      const conversation = await unwrap(api.POST("/api/conversations", { body: { agentId } }));
      const sent = await unwrap(
        api.POST("/api/conversations/{conversation_id}/messages", {
          params: { path: { conversation_id: conversation.id } },
          body: { content },
        }),
      );
      return { conversation, ...sent };
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.list }),
  });
}

export function useSendMessage(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      unwrap(
        api.POST("/api/conversations/{conversation_id}/messages", {
          params: { path: { conversation_id: conversationId } },
          body: { content },
        }),
      ),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) }),
        queryClient.invalidateQueries({ queryKey: conversationKeys.list }),
      ]),
  });
}

export function useRenameConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      unwrap(
        api.PATCH("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
          body: { title },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: conversationKeys.list }),
        queryClient.invalidateQueries({ queryKey: runKeys.all }),
      ]),
  });
}

export function useCancelRun() {
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap(api.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: runId } } })),
  });
}

export function useRuns(params: RunListParams) {
  return useQuery({
    queryKey: runKeys.list(params),
    queryFn: () => unwrap(api.GET("/api/runs", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
}
