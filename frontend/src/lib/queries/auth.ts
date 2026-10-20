import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { clearToken, getToken, setToken } from "@/lib/auth";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => unwrap(api.GET("/api/auth/me")),
    enabled: getToken() !== null,
    retry: false,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      unwrap(api.POST("/api/auth/login", { body })),
    onSuccess: (data) => {
      setToken(data.accessToken);
      queryClient.clear();
      queryClient.setQueryData(["me"], data.user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return () => {
    clearToken();
    queryClient.clear();
  };
}
