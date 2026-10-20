// Access token storage. localStorage can be unavailable (private mode, blocked storage),
// so every access is guarded. Subscribers are notified when the token changes so the
// app shell can react (e.g. redirect to /login after a 401).

const TOKEN_KEY = "agent-manager.token";
const listeners = new Set<() => void>();

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore: the session simply won't survive a reload
  }
  notify();
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
  notify();
}

/** `useSyncExternalStore`-compatible subscription to token changes. */
export function subscribeToken(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify() {
  for (const listener of listeners) listener();
}
