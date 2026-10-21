"use client";

import { Bot, LogOut, MessageSquare, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Me } from "@/lib/api/client";
import { getToken, subscribeToken } from "@/lib/auth";
import { useLogout, useMe } from "@/lib/queries/auth";
import { cn } from "@/lib/utils";

/** Authenticated page chrome. Redirects to /login when there is no session. */
export function AppShell({
  children,
  adminOnly = false,
}: {
  children: (me: Me) => React.ReactNode;
  adminOnly?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const hasToken = useSyncExternalStore(
    subscribeToken,
    () => getToken() !== null,
    () => false,
  );
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
  const me = useMe();
  const logout = useLogout();

  useEffect(() => {
    if (mounted && (!hasToken || me.isError)) router.replace("/login");
  }, [mounted, hasToken, me.isError, router]);

  if (!mounted || !me.data) {
    return (
      <div className="mx-auto w-full max-w-6xl space-y-4 p-6">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const nav = [
    { href: "/agents", label: "Agents", icon: Bot, show: true },
    { href: "/chat", label: "Chat", icon: MessageSquare, show: true },
    { href: "/settings/teams", label: "Teams & Users", icon: Users, show: me.data.role === "admin" },
  ];

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-4">
          <Link href="/agents" className="font-semibold">
            Agent Manager
          </Link>
          <nav className="flex gap-1">
            {nav
              .filter((item) => item.show)
              .map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                    pathname.startsWith(item.href) && "bg-muted text-foreground",
                  )}
                >
                  <item.icon className="size-4" />
                  {item.label}
                </Link>
              ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-muted-foreground">
              {me.data.name}
              {me.data.role === "admin" && " (admin)"}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                logout();
                router.replace("/login");
              }}
            >
              <LogOut className="size-4" />
              Log out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {adminOnly && me.data.role !== "admin" ? (
          <p className="text-muted-foreground">You need admin permissions to view this page.</p>
        ) : (
          children(me.data)
        )}
      </main>
    </div>
  );
}

function noopSubscribe() {
  return () => {};
}
