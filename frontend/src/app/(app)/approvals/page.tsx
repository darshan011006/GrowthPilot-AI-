"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth, useCan } from "@/components/auth";
import { ConnectionBadge, EvidenceBadge, SourceLink, SyntheticBadge, ValidationPanel } from "@/components/domain";
import { PostPreview } from "@/components/post-preview";
import { Alert, Badge, Button, Card, Empty, Loading, PageHeader, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { ContentItem } from "@/lib/types";

function ApprovalCard({ item, mode, liveEnabled, onDone }: { item: ContentItem; mode: string; liveEnabled: boolean; onDone: () => void }) {
  const can = useCan();
  const { state } = useAuth();
  const [ack, setAck] = useState(false);
  const [authorize, setAuthorize] = useState(false);
  const [note, setNote] = useState("");
  const [showChanges, setShowChanges] = useState(false);
  const act = useAction();
  const v = item.validation;
  const warnings = v ? [...v.product_claims, ...v.brand, ...v.platform].filter((c) => c.status === "warn") : [];
  const failures = v?.failures ?? 0;
  const hasLiveTarget = (item.target_connections || []).some((c) => c.adapter_info?.external);

  const approve = async () => {
    const r = await act.run(() => api.post(`/api/content/${item.id}/approve`, { version: item.version, acknowledge_warnings: ack, authorize_publish: authorize }));
    if (r) onDone();
  };
  const changes = async () => {
    const r = await act.run(() => api.post(`/api/content/${item.id}/request-changes`, { note }));
    if (r) onDone();
  };

  return (
    <Card>
      <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <PostPreview assets={item.assets || []} caption={item.final_caption || ""} account={state?.workspace?.name || "brand"} type={item.content_type} />
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/content/${item.id}`} className="text-lg font-semibold hover:underline">{item.title}</Link>
            <Badge>v{item.version}</Badge><Badge>{item.platform} {item.content_type}</Badge>{item.variant_label && <Badge tone="info">variant {item.variant_label}</Badge>}
            <SyntheticBadge show={item.is_synthetic} label="Demo" />
          </div>
          <div className="grid gap-3 text-sm md:grid-cols-2">
            <div><div className="text-xs font-semibold uppercase text-muted">Intended publication</div>{fmtDate(item.planned_at, can.tz)} <span className="text-muted">({can.tz})</span></div>
            <div><div className="text-xs font-semibold uppercase text-muted">Target account</div>
              {(item.target_connections || []).length === 0 ? <span className="text-warn">No verified connection</span> :
                item.target_connections!.map((c) => <div key={c.id} className="flex items-center gap-1.5">{c.account_label || c.name}<ConnectionBadge status={c.status} /></div>)}</div>
            {item.campaign && <div className="md:col-span-2"><div className="text-xs font-semibold uppercase text-muted">Campaign objective</div><Link href={`/campaigns/${item.campaign.id}`} className="hover:underline">{item.campaign.objective || item.campaign.name}</Link></div>}
            {item.hypothesis && <div className="md:col-span-2"><div className="text-xs font-semibold uppercase text-muted">Hypothesis being tested</div>{item.hypothesis.statement}</div>}
            {item.products && item.products.length > 0 && <div className="md:col-span-2"><div className="text-xs font-semibold uppercase text-muted">Products featured</div>{item.products.map((p) => p.name).join(", ")}</div>}
          </div>
          {item.evidence && item.evidence.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-xs font-semibold uppercase text-muted">Supporting evidence ({item.evidence.length})</summary>
              <ul className="mt-2 space-y-1.5">
                {item.evidence.map((f) => (
                  <li key={f.id} className="flex flex-wrap items-center gap-1.5"><EvidenceBadge c={f.classification} /><SyntheticBadge show={f.is_synthetic} /> {f.statement.slice(0, 200)} <span className="text-xs text-muted">— <SourceLink f={f} /></span></li>
                ))}
              </ul>
            </details>
          )}
          <div className="rounded-lg border border-line p-3"><ValidationPanel v={v} version={item.version} /></div>

          {can.own ? (
            <div className="space-y-2">
              {warnings.length > 0 && (
                <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-1" />
                  I&apos;ve reviewed the {warnings.length} warning(s) above.</label>
              )}
              {mode === "live" && hasLiveTarget && (
                <label className="flex items-start gap-2 text-sm text-bad"><input type="checkbox" checked={authorize} onChange={(e) => setAuthorize(e.target.checked)} className="mt-1" />
                  Also authorise publishing this exact version (v{item.version}) to the real account. {liveEnabled ? "" : "(Live publishing is currently off.)"}</label>
              )}
              {act.error && <Alert tone="bad">{act.error}</Alert>}
              <div className="flex flex-wrap gap-2">
                <Button variant="ok" busy={act.busy} disabled={failures > 0 || (warnings.length > 0 && !ack)} onClick={approve}>Approve v{item.version}</Button>
                <Button onClick={() => setShowChanges(!showChanges)}>Request changes</Button>
                <Link href={`/content/${item.id}`} className="rounded-lg border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">Edit</Link>
              </div>
              {failures > 0 && <p className="text-xs text-bad">Can&apos;t approve: {failures} validation failure(s). Edit the post first.</p>}
              {showChanges && (
                <div className="space-y-2">
                  <Textarea aria-label="What should change?" placeholder="What should change?" value={note} onChange={(e) => setNote(e.target.value)} />
                  <Button variant="danger" busy={act.busy} disabled={!note.trim()} onClick={changes}>Send back</Button>
                </div>
              )}
            </div>
          ) : <Alert tone="info">Only a workspace owner can approve.</Alert>}
        </div>
      </div>
    </Card>
  );
}

export default function ApprovalsPage() {
  const { data, loading, error, reload } = useApi<{ items: ContentItem[]; live_publishing_enabled: boolean; mode: string }>("/api/approvals");
  return (
    <div>
      <PageHeader title="Approval Inbox" subtitle="Nothing is scheduled or published until a person approves the exact version shown here. Editing an approved post sends it back for approval." />
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.items.length ? (
        <Empty title="Nothing waiting for approval">When the agent finishes a campaign it sends validated posts here.</Empty>
      ) : (
        <div className="space-y-5">
          <p className="text-sm text-muted">{data.items.length} post(s) waiting.</p>
          {data.items.map((i) => <ApprovalCard key={`${i.id}-${i.version}`} item={i} mode={data.mode} liveEnabled={data.live_publishing_enabled} onDone={reload} />)}
        </div>
      )}
    </div>
  );
}
