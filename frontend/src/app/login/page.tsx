"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLogin } from "@/lib/queries/auth";

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Agent Manager</CardTitle>
          <CardDescription>Sign in to manage your agents.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              login.mutate({ email, password }, { onSuccess: () => router.replace("/agents") });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {login.error && <p className="text-sm text-destructive">{login.error.message}</p>}
            <Button type="submit" className="w-full" disabled={login.isPending}>
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
            <p className="text-xs text-muted-foreground">
              Dev seed: admin@example.com, alice@example.com, bob@example.com / password123
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
