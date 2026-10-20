import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

const teamKeys = {
  all: ["teams"] as const,
  users: ["users"] as const,
};

export function useTeams() {
  return useQuery({
    queryKey: teamKeys.all,
    queryFn: () => unwrap(api.GET("/api/teams")),
  });
}

export function useUsers() {
  return useQuery({
    queryKey: teamKeys.users,
    queryFn: () => unwrap(api.GET("/api/users")),
  });
}

export function useCreateTeam() {
  const invalidate = useInvalidateTeams();
  return useMutation({
    mutationFn: (body: Schemas["TeamCreate"]) => unwrap(api.POST("/api/teams", { body })),
    onSuccess: invalidate,
  });
}

export function useDeleteTeam() {
  const invalidate = useInvalidateTeams();
  return useMutation({
    mutationFn: (teamId: string) =>
      unwrap(api.DELETE("/api/teams/{team_id}", { params: { path: { team_id: teamId } } })),
    onSuccess: invalidate,
  });
}

export function useUpsertTeamMember() {
  const invalidate = useInvalidateTeams();
  return useMutation({
    mutationFn: (args: { teamId: string; userId: string; role: "member" | "team_admin" }) =>
      unwrap(
        api.PUT("/api/teams/{team_id}/members/{user_id}", {
          params: { path: { team_id: args.teamId, user_id: args.userId } },
          body: { role: args.role },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useRemoveTeamMember() {
  const invalidate = useInvalidateTeams();
  return useMutation({
    mutationFn: (args: { teamId: string; userId: string }) =>
      unwrap(
        api.DELETE("/api/teams/{team_id}/members/{user_id}", {
          params: { path: { team_id: args.teamId, user_id: args.userId } },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["UserCreate"]) => unwrap(api.POST("/api/users", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: teamKeys.users }),
  });
}

function useInvalidateTeams() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: teamKeys.all }),
      // Team membership changes what the current user can see and do.
      queryClient.invalidateQueries({ queryKey: ["me"] }),
      queryClient.invalidateQueries({ queryKey: ["agents"] }),
    ]);
}
