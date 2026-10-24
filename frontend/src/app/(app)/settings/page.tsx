"use client";

import { useState } from "react";
import { useAuth, useCan } from "@/components/auth";
import { Alert, Badge, Button, Card, Field, Input, KeyValue, Loading, PageHeader, Select, Tabs, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtNum } from "@/lib/format";

interface SettingsData {
  workspace: { id: number; name: string; timezone: string; agent_max_steps: number; agent_token_budget: number; agent_timeout_minutes: number };
  members: { id: number; user_id: number; name: string; email: string; role: string }[];
  invites: { id: number; email: string; role: string; expires_at: string }[];
  role: string;
  timezones: string[];
}
interface System { mode: string; env: string; database: string; database_kind: string; worker: string; live_publishing_enabled: boolean; secure_cookies: boolean; config_problems: { key: string; impact: string }[] }
interface AuditRow { id: number; action: string; target_type: string; target_id: string | null; details: Record<string, unknown>; user: string; ip: string | null; created_at: string }

type Tab = "workspace" | "members" | "audit" | "system";

export default function SettingsPage() {
  const can = useCan();
  const { state, refresh } = useAuth();
  const [tab, setTab] = useState<Tab>("workspace");
  const { data, loading, error, reload } = useApi<SettingsData>("/api/settings");
  const sys = useApi<System>("/api/system");
  const audit = useApi<{ rows: AuditRow[] }>(tab === "audit" && can.own ? "/api/settings/audit" : null);
  const [wsEdit, setWs] = useState<SettingsData["workspace"] | null>(null);
  const [inv, setInv] = useState({ email: "", role: "editor" });
  const [link, setLink] = useState<string | null>(null);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [resetText, setResetText] = useState("");
  const act = useAction();
  const [ok, setOk] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  const ws = wsEdit ?? data.workspace; // local edits, else the saved values

  const done = (msg: string) => { setOk(msg); setTimeout(() => setOk(null), 4000); };

  return (
    <div>
      <PageHeader title="Settings" />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "workspace", label: "Workspace & agent" }, { id: "members", label: "Members", count: data.members.length }, { id: "audit", label: "Audit log" }, { id: "system", label: "System health" }]} />
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      {ok && <div className="mb-3"><Alert tone="ok">{ok}</Alert></div>}

      {tab === "workspace" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Workspace">
            <fieldset disabled={!can.own}>
              <Field label="Name">{(id) => <Input id={id} value={ws.name} onChange={(e) => setWs({ ...ws, name: e.target.value })} />}</Field>
              <Field label="Time zone" hint="used for scheduling and the calendar">{(id) => <Select id={id} value={ws.timezone} onChange={(e) => setWs({ ...ws, timezone: e.target.value })}>{data.timezones.map((t) => <option key={t}>{t}</option>)}</Select>}</Field>
              <div className="mb-2 mt-4 text-sm font-semibold">Agent execution limits (per run)</div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Max tool steps">{(id) => <Input id={id} type="number" min={5} max={200} value={ws.agent_max_steps} onChange={(e) => setWs({ ...ws, agent_max_steps: Number(e.target.value) })} />}</Field>
                <Field label="Token budget">{(id) => <Input id={id} type="number" min={10000} step={10000} value={ws.agent_token_budget} onChange={(e) => setWs({ ...ws, agent_token_budget: Number(e.target.value) })} />}</Field>
                <Field label="Timeout (min)">{(id) => <Input id={id} type="number" min={1} max={120} value={ws.agent_timeout_minutes} onChange={(e) => setWs({ ...ws, agent_timeout_minutes: Number(e.target.value) })} />}</Field>
              </div>
              {can.own && <Button variant="primary" busy={act.busy} onClick={async () => { const { id, ...body } = ws; void id; if (await act.run(() => api.put("/api/settings", body))) { done("Saved."); setWs(null); refresh(); reload(); } }}>Save</Button>}
            </fieldset>
          </Card>
          <Card title="Your password">
            <Field label="Current password">{(id) => <Input id={id} type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />}</Field>
            <Field label="New password" hint="10+ chars, mixed case, a number">{(id) => <Input id={id} type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />}</Field>
            <Button busy={act.busy} onClick={async () => { if (await act.run(() => api.post("/api/auth/password", pw))) { setPw({ current_password: "", new_password: "" }); done("Password changed. Other sessions were signed out."); } }}>Change password</Button>
          </Card>
          {state?.mode === "demo" && can.own && (
            <Card title="Demo data reset" className="lg:col-span-2">
              <p className="mb-2 text-sm text-muted">Deletes this workspace&apos;s marketing data (brand, products, campaigns, content, runs, metrics) and reloads the fictional demo brand. Users and settings are kept. Demo mode only.</p>
              <div className="flex flex-wrap items-center gap-2">
                <Input aria-label="Type RESET to confirm" placeholder="Type RESET" value={resetText} onChange={(e) => setResetText(e.target.value)} className="max-w-40" />
                <Button variant="danger" busy={act.busy} disabled={resetText !== "RESET"} onClick={async () => { if (await act.run(() => api.post("/api/demo/reset", { confirm: "RESET" }))) { setResetText(""); done("Demo data reset."); } }}>Reset demo data</Button>
              </div>
            </Card>
          )}
        </div>
      )}

      {tab === "members" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Members" subtitle="Owners approve, authorise publishing and manage integrations. Editors create content and run the agent. Viewers read only. Enforced by the backend.">
            <ul className="divide-y divide-line text-sm">
              {data.members.map((m) => (
                <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span><strong>{m.name}</strong> <span className="text-muted">{m.email}</span></span>
                  {can.own ? (
                    <span className="flex gap-2">
                      <Select aria-label={`Role for ${m.name}`} className="w-auto" value={m.role} onChange={async (e) => { await act.run(() => api.put(`/api/settings/members/${m.id}`, { role: e.target.value })); reload(); }}>
                        {["owner", "editor", "viewer"].map((r) => <option key={r}>{r}</option>)}
                      </Select>
                      <Button size="sm" variant="ghost" onClick={async () => { if (confirm(`Remove ${m.name}?`)) { await act.run(() => api.del(`/api/settings/members/${m.id}`)); reload(); } }}>Remove</Button>
                    </span>
                  ) : <Badge>{m.role}</Badge>}
                </li>
              ))}
            </ul>
          </Card>
          {can.own && (
            <Card title="Invite someone" subtitle="There's no email sending; share the one-time link directly.">
              <Field label="Email">{(id) => <Input id={id} type="email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} />}</Field>
              <Field label="Role">{(id) => <Select id={id} value={inv.role} onChange={(e) => setInv({ ...inv, role: e.target.value })}>{["editor", "viewer", "owner"].map((r) => <option key={r}>{r}</option>)}</Select>}</Field>
              <Button variant="primary" busy={act.busy} onClick={async () => { const r = await act.run(() => api.post<{ link: string }>("/api/settings/invites", inv)); if (r) { setLink(r.link); reload(); } }}>Create invite link</Button>
              {link && <div className="mt-3"><Alert tone="warn" title="Shown once — copy it now"><code className="break-all text-xs">{link}</code></Alert></div>}
              {data.invites.length > 0 && (
                <ul className="mt-4 space-y-1 text-sm">
                  {data.invites.map((i) => <li key={i.id} className="flex items-center justify-between">{i.email} · {i.role} <span className="text-xs text-muted">expires {fmtDate(i.expires_at, can.tz, false)}</span>
                    <Button size="sm" variant="ghost" onClick={async () => { await act.run(() => api.del(`/api/settings/invites/${i.id}`)); reload(); }}>Revoke</Button></li>)}
                </ul>
              )}
            </Card>
          )}
        </div>
      )}

      {tab === "audit" && (
        <Card title="Audit log" subtitle="Approvals, scheduling, publishing, logins and configuration changes. Secrets are never logged.">
          {!can.own ? <Alert tone="info">Only owners can view the audit log.</Alert> : audit.loading && !audit.data ? <Loading /> : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">When</th><th className="pr-3">Who</th><th className="pr-3">Action</th><th className="pr-3">Target</th><th>Details</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {audit.data?.rows.map((r) => (
                    <tr key={r.id} className="align-top">
                      <td className="whitespace-nowrap py-1.5 pr-3 text-muted">{fmtDate(r.created_at, can.tz)}</td>
                      <td className="pr-3">{r.user}</td>
                      <td className="pr-3 font-semibold">{r.action}</td>
                      <td className="pr-3">{r.target_type} {r.target_id}</td>
                      <td className="max-w-md break-all text-muted">{Object.keys(r.details).length ? JSON.stringify(r.details) : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {tab === "system" && (
        <Card title="System health">
          {!sys.data ? <Loading /> : (
            <>
              <KeyValue items={[
                ["Mode", <Badge key="m" tone={sys.data.mode === "demo" ? "demo" : "ok"}>{sys.data.mode}</Badge>], ["Environment", sys.data.env],
                ["Database", `${sys.data.database} (${sys.data.database_kind})`], ["Worker", sys.data.worker],
                ["Live publishing", sys.data.live_publishing_enabled ? "ON" : "off"], ["Secure cookies", sys.data.secure_cookies ? "yes (HTTPS)" : "no — use HTTPS in production"],
                ["Agent budget", `${fmtNum(ws.agent_max_steps)} steps · ${fmtNum(ws.agent_token_budget)} tokens · ${ws.agent_timeout_minutes} min`],
              ]} />
              {sys.data.config_problems.length > 0 && <div className="mt-3"><Alert tone="warn" title="Configuration gaps">{sys.data.config_problems.map((p) => <div key={p.key}><code>{p.key}</code>: {p.impact}</div>)}</Alert></div>}
              <p className="mt-3 text-xs text-muted">Troubleshooting: see README → Troubleshooting. API docs at <a className="underline" href="/api/docs">/api/docs</a> (development only).</p>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
