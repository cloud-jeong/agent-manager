import createClient, { type Middleware } from "openapi-fetch";

import { clearToken, getToken } from "@/lib/auth";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Agent = Schemas["AgentRead"];
export type AgentCreate = Schemas["AgentCreate"];
export type AgentUpdate = Schemas["AgentUpdate"];
export type AgentScope = Agent["scope"];
export type Team = Schemas["TeamRead"];
export type User = Schemas["UserRead"];
export type Me = Schemas["MeRead"];
export type Conversation = Schemas["ConversationRead"];
export type ConversationDetail = Schemas["ConversationDetail"];
export type ChatMessage = Schemas["MessageRead"];
export type Run = Schemas["RunRead"];
export type RunDetail = Schemas["RunDetail"];
export type RunStatus = Run["status"];
export type McpServer = Schemas["McpServerRead"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Error thrown for non-2xx responses; message comes from `{ error: { message } }`. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response, request }) {
    // An expired/invalid session: drop the token; AppShell redirects to /login.
    if (response.status === 401 && !request.url.endsWith("/api/auth/login")) {
      clearToken();
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: API_URL });
api.use(authMiddleware);

/** Unwrap an openapi-fetch result, throwing `ApiError` on failure. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || !response.ok) {
    throw new ApiError(response.status, errorMessage(error) ?? response.statusText);
  }
  return data as T;
}

function errorMessage(error: unknown): string | undefined {
  if (error && typeof error === "object" && "error" in error) {
    const inner = (error as { error?: { message?: unknown } }).error;
    if (typeof inner?.message === "string") return inner.message;
  }
  return undefined;
}
