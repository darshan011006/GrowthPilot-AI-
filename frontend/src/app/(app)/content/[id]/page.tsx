"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useAuth, useCan } from "@/components/auth";
import { ContentStatusBadge, SyntheticBadge, ValidationPanel } from "@/components/domain";
import { PostPreview } from "@/components/post-preview";
import { Alert, Badge, Button, Card, Field, Input, ListInput, Loading, Modal, PageHeader, Select, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtNum, toLocalInput } from "@/lib/format";
import type { Asset, Connection, ContentItem, Product } from "@/lib/types";

const EDITABLE = ["draft", "in_review", "changes_requested", "approved", "scheduled", "failed"];

function pick(item: ContentItem): Partial<ContentItem> {
  return { hook: item.hook, caption: item.caption, hashtags: item.hashtags, cta: item.cta, title: item.title, pillar: item.pillar,
    content_type: item.content_type, image_brief: item.image_brief, carousel_outline: item.carousel_outline, product_ids: item.product_ids,
    asset_id: item.asset_id };
}

export default function ContentEditor() {
  const { id } = useParams<{ id: string }>();
  const { data: item, error, loading, setData } = useApi<ContentItem>(`/api/content/${id}`);
  if (loading && !item) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!item) return null;
  // Remount the editor whenever a new version/status arrives, so local edits start from the saved item.
  return <Editor key={`${item.id}-${item.version}-${item.status}`} item={item} setData={setData} />;
}

function Editor({ item, setData }: { item: ContentItem; setData: (i: ContentItem) => void }) {
  const id = item.id;
  const can = useCan();
  const { state } = useAuth();
  const products = useApi<Product[]>("/api/products");
  const assets = useApi<Asset[]>("/api/assets");
  const integ = useApi<{ connections: Connection[]; live_publishing_enabled: boolean }>("/api/integrations");
  const [draft, setDraft] = useState<Partial<ContentItem>>(() => pick(item));
  const [regenOpen, setRegenOpen] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [schedState, setSched] = useState(() => ({ connection_id: "", when: toLocalInput(item.planned_at, can.tz), confirm: false }));
  const act = useAction();

  const conns = useMemo(() => (integ.data?.connections || []).filter((c) => c.available_in_mode && ["connected", "demo"].includes(c.status) && (c.platform === "any" || c.platform === item.platform)), [integ.data, item.platform]);
  const sched = { ...schedState, connection_id: schedState.connection_id || (conns[0] ? String(conns[0].id) : "") };

  const editable = can.edit && EDITABLE.includes(item.status);
  const dirty = JSON.stringify(draft) !== JSON.stringify(pick(item));
  const doAct = async (fn: () => Promise<ContentItem | { item: ContentItem }>) => {
    const r = await act.run(fn);
    if (r) setData("item" in r ? r.item : r);
  };
  const save = () => doAct(() => api.put<ContentItem>(`/api/content/${id}`, draft));
  const selectedConn = conns.find((c) => String(c.id) === sched.connection_id);
  const liveTarget = !!selectedConn?.adapter_info?.external;
  const previewCaption = item.final_caption || "";

  return (
    <div>
      <PageHeader title={item.title || `Post #${item.id}`}
        subtitle={<span className="flex flex-wrap items-center gap-2"><ContentStatusBadge status={item.status} /> v{item.version} · {item.platform} {item.content_type}
          {item.campaign_id && <> · <Link href={`/campaigns/${item.campaign_id}`} className="text-accent hover:underline">{item.campaign_name}</Link></>}
          {item.variant_label && <Badge>variant {item.variant_label}</Badge>}<SyntheticBadge show={item.is_synthetic} label="Demo" />
          {item.generated_by !== "human" && <Badge>{item.generated_by}</Badge>}</span>} />
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      {item.review_note && <div className="mb-3"><Alert tone="warn" title="Reviewer note">{item.review_note}</Alert></div>}
      {item.last_error && <div className="mb-3"><Alert tone={item.status === "failed" ? "bad" : "warn"}>{item.last_error}</Alert></div>}
      {item.approved_version && item.approved_version !== item.version && <div className="mb-3"><Alert tone="warn">Approved version was v{item.approved_version}; this is v{item.version}. It needs approval again.</Alert></div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <Card title="Content" actions={editable && <>
            <Button size="sm" onClick={() => setRegenOpen(true)}>Regenerate</Button>
            <Button size="sm" variant="primary" busy={act.busy} disabled={!dirty} onClick={save}>Save as v{item.version + 1}</Button></>}>
            {!editable && <p className="mb-2 text-xs text-muted">This item can&apos;t be edited in its current status.</p>}
            <fieldset disabled={!editable} className="grid gap-x-4 md:grid-cols-2">
              <Field label="Internal title">{(fid) => <Input id={fid} value={draft.title || ""} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />}</Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Type">{(fid) => <Select id={fid} value={draft.content_type} onChange={(e) => setDraft({ ...draft, content_type: e.target.value })}>{["post", "carousel", "reel", "story"].map((t) => <option key={t}>{t}</option>)}</Select>}</Field>
                <Field label="Pillar">{(fid) => <Input id={fid} value={draft.pillar || ""} onChange={(e) => setDraft({ ...draft, pillar: e.target.value })} />}</Field>
              </div>
              <div className="md:col-span-2"><Field label="Hook">{(fid) => <Input id={fid} value={draft.hook || ""} onChange={(e) => setDraft({ ...draft, hook: e.target.value })} />}</Field></div>
              <div className="md:col-span-2"><Field label="Caption">{(fid) => <Textarea id={fid} rows={7} value={draft.caption || ""} onChange={(e) => setDraft({ ...draft, caption: e.target.value })} />}</Field></div>
              <Field label="Call to action">{(fid) => <Input id={fid} value={draft.cta || ""} onChange={(e) => setDraft({ ...draft, cta: e.target.value })} />}</Field>
              <Field label="Hashtags" hint="space separated">{(fid) => <Input id={fid} value={(draft.hashtags || []).join(" ")} onChange={(e) => setDraft({ ...draft, hashtags: e.target.value.split(/\s+/).filter(Boolean) })} />}</Field>
              <Field label="Products featured" hint="claims are checked against these">{(fid) => (
                <select id={fid} multiple className="h-28 w-full rounded-lg border border-line bg-panel px-2 py-1 text-sm" value={(draft.product_ids || []).map(String)}
                  onChange={(e) => setDraft({ ...draft, product_ids: Array.from(e.target.selectedOptions).map((o) => Number(o.value)) })}>
                  {products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>)}</Field>
              <Field label="Cover image">{(fid) => (
                <Select id={fid} value={draft.asset_id ?? ""} onChange={(e) => setDraft({ ...draft, asset_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">None</option>
                  {assets.data?.map((a) => <option key={a.id} value={a.id}>{a.placeholder ? "Placeholder: " : ""}{a.filename}</option>)}
                </Select>)}</Field>
              <div className="md:col-span-2"><Field label="Image brief">{(fid) => <Textarea id={fid} value={draft.image_brief || ""} onChange={(e) => setDraft({ ...draft, image_brief: e.target.value })} />}</Field></div>
              {draft.content_type === "carousel" && <div className="md:col-span-2"><Field label="Carousel outline" hint="one slide per line">{() => <ListInput value={draft.carousel_outline || []} onChange={(v) => setDraft({ ...draft, carousel_outline: v })} rows={5} />}</Field></div>}
            </fieldset>
            {item.rationale && <p className="mt-2 text-xs text-muted">Rationale: {item.rationale}</p>}
          </Card>

          <Card title="Validation" actions={<Button size="sm" busy={act.busy} onClick={async () => { const v = await act.run(() => api.post(`/api/content/${id}/validate`)); if (v) setData({ ...item, validation: v as ContentItem["validation"] }); }}>Re-check</Button>}>
            <ValidationPanel v={item.validation} version={item.version} />
          </Card>

          <Card title="Version history">
            <ul className="divide-y divide-line text-sm">
              {item.revisions?.map((r) => (
                <li key={r.version} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                  <span><strong>v{r.version}</strong> · {r.source} {r.note && <span className="text-muted">— {r.note}</span>}{item.approved_version === r.version && <Badge tone="accent" className="ml-1">approved</Badge>}</span>
                  <span className="flex items-center gap-2 text-xs text-muted">{fmtDate(r.created_at, can.tz)}
                    {editable && r.version !== item.version && <Button size="sm" variant="ghost" onClick={() => doAct(() => api.post<ContentItem>(`/api/content/${id}/restore`, { version: r.version }))}>Restore</Button>}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="space-y-5">
          <Card title="Preview"><PostPreview assets={item.assets || []} caption={previewCaption} account={state?.workspace?.name || "brand"} type={item.content_type} /></Card>
          <Card title="Workflow">
            <div className="space-y-2 text-sm">
              <div>Planned: {fmtDate(item.planned_at, can.tz)}</div>
              {item.scheduled_at && <div>Scheduled: {fmtDate(item.scheduled_at, can.tz)} via {item.connection_name}</div>}
              {item.published_at && <div>Published: {fmtDate(item.published_at, can.tz)} {item.publish_verified ? <Badge tone="ok">verified by provider</Badge> : <Badge tone="warn">not verified</Badge>}</div>}
              {item.external_url && <a href={item.external_url} target="_blank" rel="noopener noreferrer" className="text-info hover:underline">View post ↗</a>}
              <div className="flex flex-wrap gap-2 pt-1">
                {can.edit && ["draft", "changes_requested"].includes(item.status) && <Button variant="primary" busy={act.busy} disabled={dirty} onClick={() => doAct(() => api.post<ContentItem>(`/api/content/${id}/submit`))}>Submit for review</Button>}
                {item.status === "in_review" && <Link href="/approvals" className="rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-accent-ink">Review in Approval Inbox</Link>}
                {can.own && item.status === "scheduled" && <>
                  <Button busy={act.busy} onClick={() => doAct(() => api.post<ContentItem>(`/api/content/${id}/unschedule`))}>Unschedule</Button>
                  <Button variant={item.connection_live ? "danger" : "primary"} busy={act.busy} onClick={() => {
                    const live = item.connection_live;
                    if (live && !confirm("This publishes to a REAL account now. Continue?")) return;
                    void doAct(() => api.post<ContentItem>(`/api/content/${id}/publish-now`, { confirm: live }));
                  }}>Publish now</Button></>}
                {item.status === "published" && <Button size="sm" busy={act.busy} onClick={() => doAct(() => api.post<{ item: ContentItem }>(`/api/content/${id}/verify`))}>Re-verify with provider</Button>}
                {can.edit && !["published", "publishing", "cancelled"].includes(item.status) && <Button variant="ghost" onClick={() => { if (confirm("Cancel this post?")) void doAct(() => api.post<ContentItem>(`/api/content/${id}/cancel`)); }}>Cancel post</Button>}
              </div>
            </div>
            {can.own && ["approved", "failed"].includes(item.status) && item.approved_version === item.version && (
              <div className="mt-4 border-t border-line pt-3">
                <div className="mb-2 text-sm font-semibold">Schedule</div>
                {conns.length === 0 ? <Alert tone="warn">No verified connection for {item.platform}. <Link href="/integrations" className="underline">Connect one</Link>.</Alert> : <>
                  <Field label="Account">{(fid) => <Select id={fid} value={sched.connection_id} onChange={(e) => setSched({ ...sched, connection_id: e.target.value })}>{conns.map((c) => <option key={c.id} value={c.id}>{c.account_label || c.name}</option>)}</Select>}</Field>
                  <Field label="When" hint={can.tz}>{(fid) => <Input id={fid} type="datetime-local" value={sched.when} onChange={(e) => setSched({ ...sched, when: e.target.value })} />}</Field>
                  {liveTarget && (
                    <label className="mb-2 flex items-start gap-2 text-sm text-bad">
                      <input type="checkbox" checked={sched.confirm} onChange={(e) => setSched({ ...sched, confirm: e.target.checked })} className="mt-1" />
                      I understand this will publish v{item.version} to a real account at the chosen time.
                    </label>
                  )}
                  {liveTarget && !integ.data?.live_publishing_enabled && <Alert tone="warn">Live publishing is turned off (LIVE_PUBLISHING_ENABLED=false).</Alert>}
                  {liveTarget && !item.publish_authorized && <Alert tone="warn">This version was approved without publish authorisation.</Alert>}
                  <Button variant="primary" className="mt-2" busy={act.busy} disabled={liveTarget && !sched.confirm}
                    onClick={() => doAct(() => api.post<ContentItem>(`/api/content/${id}/schedule`, { connection_id: Number(sched.connection_id), when: sched.when || null, confirm: sched.confirm }))}>Schedule</Button>
                </>}
              </div>
            )}
          </Card>
          {(item.attempts?.length || 0) > 0 && (
            <Card title="Publishing attempts">
              <ul className="space-y-2 text-xs">
                {item.attempts!.map((a) => (
                  <li key={a.id}><div className="flex flex-wrap items-center gap-1.5">{a.success ? <Badge tone="ok">success</Badge> : <Badge tone="bad">failed</Badge>}<Badge tone={a.live ? "bad" : "demo"}>{a.live ? "LIVE" : "simulated"}</Badge><span className="text-muted">{a.adapter} · {fmtDate(a.attempted_at, can.tz)}</span></div>
                    <div className="mt-0.5">{a.summary || a.error}</div>{a.provider_status && <div className="text-muted">Provider status: {a.provider_status}</div>}</li>
                ))}
              </ul>
            </Card>
          )}
          {(item.metrics?.length || 0) > 0 && (
            <Card title="Metrics">
              {(() => { const m = item.metrics![item.metrics!.length - 1]; return (
                <div className="text-sm"><div className="mb-1"><Badge tone={m.source === "synthetic" ? "demo" : "ok"}>{m.source}</Badge> <span className="text-xs text-muted">{fmtDate(m.captured_at, can.tz)}</span></div>
                  <div className="grid grid-cols-3 gap-2">{(["reach", "views", "likes", "comments", "shares", "saves"] as const).map((k) => <div key={k}><div className="text-xs text-muted">{k}</div><div className="font-semibold">{fmtNum(m[k])}</div></div>)}</div></div>
              ); })()}
            </Card>
          )}
        </div>
      </div>

      <Modal open={regenOpen} onClose={() => setRegenOpen(false)} title="Regenerate caption">
        <p className="mb-2 text-sm text-muted">Creates a new version. If this item was approved, it will need approval again.{state?.mode === "demo" && " In demo mode the deterministic generator produces a variation and ignores instructions."}</p>
        <Field label="Instructions (optional)">{(fid) => <Textarea id={fid} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Shorter, lead with the dimensions, no emoji" />}</Field>
        <Button variant="primary" busy={act.busy} onClick={async () => { await doAct(() => api.post<ContentItem>(`/api/content/${id}/regenerate`, { instructions })); setRegenOpen(false); }}>Regenerate</Button>
      </Modal>
    </div>
  );
}
