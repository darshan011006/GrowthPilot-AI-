"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export default function LoginPage() {
  const { state, refresh } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (state?.authenticated) router.replace("/");
    else if (state?.needs_setup) router.replace("/register");
  }, [state, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/login", { email, password });
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <div className="mb-4 flex items-center gap-2 text-lg font-bold">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm text-accent-ink">G</span> GrowthPilot AI
      </div>
      <h1 className="mb-4 text-xl font-bold">Sign in</h1>
      {error && <div className="mb-3"><Alert tone="bad">{error}</Alert></div>}
      <form onSubmit={submit}>
        <Field label="Email">{(id) => <Input id={id} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password">{(id) => <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
        <Button variant="primary" type="submit" busy={busy} className="w-full">Sign in</Button>
      </form>
      {state?.mode === "demo" && (
        <p className="mt-4 text-xs text-muted">Demo mode: if you ran <code>make demo</code>, the login is in <code>data/demo-login.txt</code>.</p>
      )}
      <p className="mt-2 text-xs text-muted">New team member? Ask a workspace owner for an invite link. <Link href="/register" className="underline">Have one?</Link></p>
    </Card>
  );
}
