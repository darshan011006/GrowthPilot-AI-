"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useAuth } from "@/components/auth";
import { Alert, Button, Card, Field, Input, Loading } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

function RegisterForm() {
  const params = useSearchParams();
  const invite = params.get("invite") || "";
  const { state, refresh } = useAuth();
  const router = useRouter();
  const [inviteInfo, setInviteInfo] = useState<{ email: string; role: string } | null>(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", workspace_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (state?.authenticated) router.replace("/");
  }, [state, router]);
  useEffect(() => {
    if (!invite) return;
    api.get<{ invite?: { email: string; role: string } }>(`/api/auth/state?invite=${encodeURIComponent(invite)}`).then((s) => {
      if (s.invite) {
        setInviteInfo(s.invite);
        setForm((f) => ({ ...f, email: s.invite!.email }));
      }
    });
  }, [invite]);

  if (!state) return <Loading />;
  const first = state.needs_setup;
  if (!first && !invite) {
    return <Card><h1 className="mb-2 text-xl font-bold">Invite only</h1><p className="text-sm text-muted">Ask a workspace owner for an invite link.</p></Card>;
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/register", { ...form, invite });
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <Card>
      <h1 className="mb-1 text-xl font-bold">{first ? "Set up GrowthPilot" : "Join the workspace"}</h1>
      <p className="mb-4 text-sm text-muted">
        {first ? "You're the first user, so you'll own this workspace. Everyone after you joins by invite." : inviteInfo ? `You've been invited as ${inviteInfo.role}.` : "Checking your invite…"}
      </p>
      {error && <div className="mb-3"><Alert tone="bad">{error}</Alert></div>}
      <form onSubmit={submit}>
        <Field label="Your name">{(id) => <Input id={id} required value={form.name} onChange={set("name")} />}</Field>
        <Field label="Email">{(id) => <Input id={id} type="email" required autoComplete="username" value={form.email} onChange={set("email")} readOnly={!!inviteInfo} />}</Field>
        <Field label="Password" hint="10+ characters, mixed case, a number">{(id) => <Input id={id} type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={set("password")} />}</Field>
        {first && <Field label="Workspace name">{(id) => <Input id={id} placeholder="Aranya Living" value={form.workspace_name} onChange={set("workspace_name")} />}</Field>}
        <Button variant="primary" type="submit" busy={busy} className="w-full">Create account</Button>
      </form>
    </Card>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<Loading />}>
      <RegisterForm />
    </Suspense>
  );
}
