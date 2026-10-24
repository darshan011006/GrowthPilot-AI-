"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useCan } from "@/components/auth";
import { ConnectionBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Field, Input, Loading, Modal, PageHeader, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { AdapterInfo, Connection } from "@/lib/types";

interface Integration {
  key: string;
  name: string;
  status: string;
  detail: string;
  env: string[];
  testable?: boolean;
  adapter?: AdapterInfo;
}

function Caps({ a }: { a: AdapterInfo }) {
  const c = a.capabilities;
  const yes = (b: boolean, l: string) => <Badge key={l} tone={b ? "ok" : "neutral"}>{b ? "✓" : "–"} {l}</Badge>;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {yes(c.oauth, "OAuth")}{yes(c.identity, "identity")}{yes(c.publish, "publish")}{yes(c.status_verification, "status check")}{yes(c.analytics, "analytics")}
      <Badge>scheduling: {c.scheduling}</Badge><Badge>{c.content_types.join(", ")}</Badge>
      <Badge tone={a.maturity === "mock" ? "demo" : a.maturity === "implemented-unverified" ? "warn" : "info"}>{a.maturity}</Badge>
    </div>
  );
}

function IntegrationsInner() {
  const can = useCan();
  const params = useSearchParams();
  const { data, loading, error, reload } = useApi<{ mode: string; live_publishing_enabled: boolean; integrations: Integration[]; connections: Connection[]; config_problems: { key: string; impact: string }[] }>("/api/integrations");
  const act = useAction();
  const [test, setTest] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [hook, setHook] = useState<{ name: string; url: string } | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  const igMsg = params.get("instagram");

  const connectInstagram = async () => {
    const r = await act.run(() => api.post<{ authorize_url: string }>("/api/integrations/instagram/start"));
    if (r) window.location.href = r.authorize_url;
  };

  return (
    <div>
      <PageHeader title="Integrations" subtitle="Each integration shows its real state. Nothing is labelled connected until the provider has confirmed the account." />
      {igMsg && <div className="mb-3"><Alert tone={igMsg === "connected" ? "ok" : "bad"}>{params.get("message")}</Alert></div>}
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      {data.mode === "demo" && <div className="mb-4"><Alert tone="demo" title="Demo mode">Integrations use demo adapters and make no external calls. Set APP_MODE=live with real credentials to connect real services. Demo and live data live in separate databases.</Alert></div>}
      {data.config_problems.length > 0 && (
        <div className="mb-4"><Alert tone="warn" title="Configuration gaps">
          <ul className="mt-1 list-disc pl-5">{data.config_problems.map((p) => <li key={p.key}><code>{p.key}</code>: {p.impact}</li>)}</ul>
        </Alert></div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {data.integrations.map((i) => (
          <Card key={i.key} title={<span className="flex flex-wrap items-center gap-2">{i.name}<ConnectionBadge status={i.status} /></span>}>
            <p className="text-sm text-muted">{i.detail}</p>
            {i.env.length > 0 && <p className="mt-2 text-xs text-muted">Environment: {i.env.map((e) => <code key={e} className="mr-1">{e}</code>)}</p>}
            {i.adapter && <Caps a={i.adapter} />}
            <div className="mt-3 flex flex-wrap gap-2">
              {i.testable && can.own && <Button size="sm" busy={act.busy} onClick={async () => { const r = await act.run(() => api.post<{ ok: boolean; message: string }>(`/api/integrations/${i.key}/test`)); if (r) setTest({ ...test, [i.key]: r }); }}>Test</Button>}
              {i.key === "instagram" && data.mode === "live" && can.own && ["awaiting_authorization", "expired", "failed", "connected"].includes(i.status) && <Button size="sm" variant="primary" busy={act.busy} onClick={connectInstagram}>{i.status === "connected" ? "Connect another account" : "Connect Instagram"}</Button>}
              {i.key === "webhook" && data.mode === "live" && can.own && <Button size="sm" onClick={() => setHook({ name: "Zapier", url: "" })}>Add webhook</Button>}
            </div>
            {test[i.key] && <div className="mt-2"><Alert tone={test[i.key].ok ? "ok" : "bad"}>{test[i.key].message}</Alert></div>}
          </Card>
        ))}
      </div>

      <Card className="mt-6" title="Connections">
        {data.connections.length === 0 ? <p className="text-sm text-muted">No connections yet.</p> : (
          <ul className="divide-y divide-line">
            {data.connections.map((c) => (
              <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 py-3 text-sm">
                <div>
                  <div className="flex flex-wrap items-center gap-2 font-semibold">{c.account_label || c.name}<ConnectionBadge status={c.status} />{!c.available_in_mode && <Badge>not usable in {data.mode} mode</Badge>}</div>
                  <div className="text-xs text-muted">{c.adapter_info?.label || c.adapter}{c.config.url && ` · ${c.config.url}`} · verified {fmtDate(c.last_verified_at, can.tz)}{c.token_expires_at && ` · token expires ${fmtDate(c.token_expires_at, can.tz, false)}`}</div>
                  {c.last_error && <div className="text-xs text-bad">{c.last_error}</div>}
                </div>
                {can.own && <div className="flex gap-2">
                  <Button size="sm" busy={act.busy} onClick={async () => { await act.run(() => api.post(`/api/connections/${c.id}/verify`)); reload(); }}>Verify</Button>
                  <Button size="sm" variant="danger" onClick={async () => { if (confirm(`Remove ${c.name}? Scheduled posts on it will be unscheduled.`)) { await act.run(() => api.del(`/api/connections/${c.id}`)); reload(); } }}>Remove</Button>
                </div>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Modal open={!!hook} onClose={() => { setHook(null); setSecret(null); reload(); }} title="Add signed webhook">
        {secret ? (
          <div>
            <Alert tone="warn" title="Copy the signing secret now">It is shown only once and stored encrypted.</Alert>
            <code className="mt-2 block break-all rounded bg-panel-2 p-2 text-xs">{secret}</code>
            <p className="mt-2 text-xs text-muted">Verify requests with HMAC-SHA256 of “timestamp.body”, sent in X-GrowthPilot-Signature. Then click Verify on the connection.</p>
          </div>
        ) : hook && (
          <div>
            <Field label="Name">{(id) => <Input id={id} value={hook.name} onChange={(e) => setHook({ ...hook, name: e.target.value })} />}</Field>
            <Field label="HTTPS URL">{(id) => <Input id={id} value={hook.url} onChange={(e) => setHook({ ...hook, url: e.target.value })} placeholder="https://hooks.zapier.com/..." />}</Field>
            <Button variant="primary" busy={act.busy} onClick={async () => { const r = await act.run(() => api.post<{ signing_secret: string }>("/api/connections/webhook", hook)); if (r) setSecret(r.signing_secret); }}>Create</Button>
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function IntegrationsPage() {
  return <Suspense fallback={<Loading />}><IntegrationsInner /></Suspense>;
}
