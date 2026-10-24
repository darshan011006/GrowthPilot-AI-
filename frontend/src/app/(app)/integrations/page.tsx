"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useCan } from "@/components/auth";
import { ConnectionBadge, PlatformChip } from "@/components/domain";
import { Alert, Badge, Button, Card, Field, Input, Loading, Modal, PageHeader, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { AdapterInfo, Connection, PlatformSpec } from "@/lib/types";

interface Integration {
  key: string;
  name: string;
  status: string;
  detail: string;
  env: string[];
  testable?: boolean;
  active?: boolean;
  maturity?: string;
  adapter?: AdapterInfo;
}

interface PlatformCard {
  key: string;
  name: string;
  status: string;
  live_adapter: string;
  connect: "oauth" | null;
  connections: Connection[];
  spec: PlatformSpec;
}

interface IntegrationsData {
  mode: string;
  live_publishing_enabled: boolean;
  ai: Integration[];
  platforms: PlatformCard[];
  other: Integration[];
  redirect_uris: Record<string, string>;
  connections: Connection[];
  config_problems: { key: string; impact: string }[];
}

const MATURITY: Record<string, [string, "ok" | "warn" | "neutral" | "info"]> = {
  "implemented-unverified": ["live adapter built, not yet verified with a real account", "warn"],
  verified: ["live adapter verified", "ok"],
  "not-implemented": ["live adapter not built yet (simulated only)", "neutral"],
};

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

function ProviderCard({ i, onTest, result, busy, canTest }: { i: Integration; onTest: () => void; result?: { ok: boolean; message: string }; busy: boolean; canTest: boolean }) {
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{i.name}<ConnectionBadge status={i.status} />{i.active && <Badge tone="accent">active</Badge>}</span>}>
      <p className="text-sm text-muted">{i.detail}</p>
      {i.env.length > 0 && <p className="mt-2 text-xs text-muted">Environment: {i.env.map((e) => <code key={e} className="mr-1">{e}</code>)}</p>}
      {i.maturity && <p className="mt-1 text-xs text-muted">Status: {i.maturity}</p>}
      {i.adapter && <Caps a={i.adapter} />}
      {i.testable && canTest && <div className="mt-3"><Button size="sm" busy={busy} onClick={onTest}>Test connection</Button></div>}
      {result && <div className="mt-2"><Alert tone={result.ok ? "ok" : "bad"}>{result.message}</Alert></div>}
    </Card>
  );
}

function PlatformTile({ p, mode, canOwn, busy, onConnect, onVerify, onRemove }: { p: PlatformCard; mode: string; canOwn: boolean; busy: boolean; onConnect: (key: string) => void; onVerify: (id: number) => void; onRemove: (c: Connection) => void }) {
  const [m, tone] = MATURITY[p.live_adapter] ?? [p.live_adapter, "neutral"];
  const sp = p.spec;
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2"><PlatformChip platform={p.key} withLabel /><ConnectionBadge status={p.status} /></span>}>
      <div className="space-y-2 text-sm">
        <Badge tone={tone}>{m}</Badge>
        <p className="text-xs text-muted">{sp.audience_note}</p>
        <div className="flex flex-wrap gap-1 text-xs">
          <Badge>{sp.content_types.join(", ")}</Badge><Badge>≤{sp.caption_max.toLocaleString("en-IN")} chars</Badge>
          {sp.hashtags_max !== null && <Badge>≤{sp.hashtags_max} hashtags</Badge>}{sp.carousel_max > 0 && <Badge>carousel ≤{sp.carousel_max}</Badge>}
          <Badge>renders {sp.render.width}×{sp.render.height}</Badge>
        </div>
        {p.connections.map((c) => (
          <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line p-2 text-xs">
            <span>{c.account_label || c.name} <ConnectionBadge status={c.status} />{c.last_error && <span className="block text-bad">{c.last_error}</span>}</span>
            {canOwn && <span className="flex gap-1"><Button size="sm" busy={busy} onClick={() => onVerify(c.id)}>Verify</Button><Button size="sm" variant="danger" onClick={() => onRemove(c)}>Remove</Button></span>}
          </div>
        ))}
        {mode === "live" && p.connect === "oauth" && canOwn && <Button size="sm" variant="primary" busy={busy} onClick={() => onConnect(p.key)}>{p.connections.length ? "Connect another" : `Connect ${sp.label}`}</Button>}
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold text-muted">Requirements & limits</summary>
          <div className="mt-1 space-y-1">
            <div><strong>Auth:</strong> {sp.auth}{sp.scopes.length > 0 && <> — <code>{sp.scopes.join(", ")}</code></>}</div>
            <div><strong>Eligibility:</strong> {sp.eligibility}</div>
            <div><strong>Publishing:</strong> {sp.publish_ops}</div>
            <div><strong>Analytics available:</strong> {sp.analytics.join(", ")}</div>
            <div><strong>Rate limits:</strong> {sp.rate_limits}</div>
            {sp.needs_from_you.length > 0 && <div><strong>Needs from you:</strong> {sp.needs_from_you.join(" · ")}</div>}
            {sp.notes.map((n) => <div key={n}>{n}</div>)}
            <div className="text-muted">Checked: {sp.verified}. {sp.sources.map((u) => <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="text-info hover:underline">docs ↗</a>)}</div>
          </div>
        </details>
      </div>
    </Card>
  );
}

function IntegrationsInner() {
  const can = useCan();
  const params = useSearchParams();
  const { data, loading, error, reload } = useApi<IntegrationsData>("/api/integrations");
  const act = useAction();
  const [test, setTest] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [hook, setHook] = useState<{ name: string; url: string } | null>(null);
  const [secret, setSecret] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  const oauthMsg = params.get("instagram") || params.get("facebook");

  const connect = async (key: string) => {
    const r = await act.run(() => api.post<{ authorize_url: string }>(`/api/integrations/${key}/start`));
    if (r) window.location.href = r.authorize_url;
  };
  const runTest = async (key: string) => {
    const r = await act.run(() => api.post<{ ok: boolean; message: string }>(`/api/integrations/${key}/test`));
    if (r) setTest({ ...test, [key]: r });
  };
  const verify = async (id: number) => { await act.run(() => api.post(`/api/connections/${id}/verify`)); reload(); };
  const remove = async (c: Connection) => { if (confirm(`Remove ${c.name}? Scheduled posts on it will be unscheduled.`)) { await act.run(() => api.del(`/api/connections/${c.id}`)); reload(); } };
  const webhooks = data.connections.filter((c) => c.adapter === "webhook");

  return (
    <div>
      <PageHeader title="Integrations" subtitle="Each integration shows its real state. Nothing is labelled connected until the provider has confirmed the account, and no platform is called live until it has been verified with a real account." />
      {oauthMsg && <div className="mb-3"><Alert tone={oauthMsg === "connected" ? "ok" : "bad"}>{params.get("message")}</Alert></div>}
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      {data.mode === "demo" && <div className="mb-4"><Alert tone="demo" title="Demo mode">All seven platforms use simulated adapters and nothing is posted anywhere. AI and search providers aren&apos;t called. Set APP_MODE=live with real keys to use them; demo and live data live in separate databases.</Alert></div>}
      {data.config_problems.length > 0 && (
        <div className="mb-4"><Alert tone="warn" title="Configuration gaps">
          <ul className="mt-1 list-disc pl-5">{data.config_problems.map((p) => <li key={p.key}><code>{p.key}</code>: {p.impact}</li>)}</ul>
        </Alert></div>
      )}

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">AI & research</h2>
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        {data.ai.map((i) => <ProviderCard key={i.key} i={i} busy={act.busy} canTest={can.own} onTest={() => runTest(i.key)} result={test[i.key]} />)}
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Publishing platforms</h2>
      {Object.keys(data.redirect_uris).length > 0 && (
        <div className="mb-3"><Alert tone="info" title="OAuth redirect URIs to register with Meta">{Object.entries(data.redirect_uris).map(([k, v]) => <div key={k}><strong>{k}:</strong> <code className="break-all">{v}</code></div>)}</Alert></div>
      )}
      <div className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.platforms.map((p) => <PlatformTile key={p.key} p={p} mode={data.mode} canOwn={can.own} busy={act.busy} onConnect={connect} onVerify={verify} onRemove={remove} />)}
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Other</h2>
      <div className="grid gap-4 md:grid-cols-2">
        {data.other.map((i) => (
          <Card key={i.key} title={<span className="flex flex-wrap items-center gap-2">{i.name}<ConnectionBadge status={i.status} /></span>}>
            <p className="text-sm text-muted">{i.detail}</p>
            {i.adapter && <Caps a={i.adapter} />}
            {webhooks.map((c) => <div key={c.id} className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs"><span>{c.name} · {c.config.url} <ConnectionBadge status={c.status} /> {fmtDate(c.last_verified_at, can.tz)}</span>
              {can.own && <span className="flex gap-1"><Button size="sm" onClick={() => verify(c.id)}>Verify</Button><Button size="sm" variant="danger" onClick={() => remove(c)}>Remove</Button></span>}</div>)}
            {data.mode === "live" && can.own && <div className="mt-3"><Button size="sm" onClick={() => setHook({ name: "Zapier", url: "" })}>Add webhook</Button></div>}
          </Card>
        ))}
      </div>

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
