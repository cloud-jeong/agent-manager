import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

const mcpServerKeys = {
  all: ["mcp-servers"] as const,
};

export function useMcpServers() {
  return useQuery({
    queryKey: mcpServerKeys.all,
    queryFn: () => unwrap(api.GET("/api/mcp-servers")),
  });
}

export function useCreateMcpServer() {
  const invalidate = useInvalidateMcpServers();
  return useMutation({
    mutationFn: (body: Schemas["McpServerCreate"]) =>
      unwrap(api.POST("/api/mcp-servers", { body })),
    onSuccess: invalidate,
  });
}

export function useDeleteMcpServer() {
  const invalidate = useInvalidateMcpServers();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/mcp-servers/{server_id}", { params: { path: { server_id: id } } })),
    onSuccess: invalidate,
  });
}

function useInvalidateMcpServers() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: mcpServerKeys.all }),
      // Deleting a server detaches it from agents.
      queryClient.invalidateQueries({ queryKey: ["agents"] }),
    ]);
}
