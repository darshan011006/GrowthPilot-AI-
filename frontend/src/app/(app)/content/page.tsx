"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useCan } from "@/components/auth";
import { ContentTile } from "@/components/content-tile";
import { ContentStatusBadge, PLATFORM_ORDER, PLATFORMS, PlatformChip, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Input, Loading, PageHeader, Select, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { cx, fmtDate } from "@/lib/format";
import type { Campaign, ContentItem } from "@/lib/types";

const STATUSES = ["", "draft", "in_review", "changes_requested", "approved", "scheduled", "published", "failed", "cancelled"];

export default function ContentList() {
  const can = useCan();
  const router = useRouter();
  const [view, setView] = useState<"gallery" | "table">("gallery");
  const [status, setStatus] = useState("");
  const [campaign, setCampaign] = useState("");
  const [platform, setPlatform] = useState("");
  const [type, setType] = useState("");
  const [mainOnly, setMainOnly] = useState(false);
  const [q, setQ] = useState("");
  const qs = new URLSearchParams({ status, content_type: type, platform, q, main_only: String(mainOnly), ...(campaign ? { campaign_id: campaign } : {}) }).toString();
  const { data, loading, error } = useApi<ContentItem[]>(`/api/content?${qs}`);
  const camps = useApi<Campaign[]>("/api/campaigns");
  const create = useAction();

  const newPost = async () => {
    const r = await create.run(() => api.post<ContentItem>("/api/content", { caption: "", content_type: "post", title: "New post" }));
    if (r) router.push(`/content/${r.id}`);
  };

  return (
    <div>
      <PageHeader title="Creative Studio" subtitle="Every post the agent or your team produced — one main post per idea plus a version per platform — with real rendered images, version history and verification."
        actions={<>
          <div role="tablist" className="flex rounded-lg border border-line p-0.5">
            {(["gallery", "table"] as const).map((v) => <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)} className={cx("rounded-md px-3 py-1 text-sm font-semibold", view === v ? "bg-accent text-accent-ink" : "text-muted")}>{v === "gallery" ? "Gallery" : "Table"}</button>)}
          </div>
          {can.edit && <Button variant="primary" busy={create.busy} onClick={newPost}>New post</Button>}
        </>} />
      {create.error && <div className="mb-3"><Alert tone="bad">{create.error}</Alert></div>}
      <Card className="mb-4">
        <div className="grid gap-3 md:grid-cols-6">
          <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace(/_/g, " ") : "All statuses"}</option>)}</Select>
          <Select aria-label="Campaign" value={campaign} onChange={(e) => setCampaign(e.target.value)}><option value="">All campaigns</option>{camps.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
          <Select aria-label="Platform" value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="">All platforms</option>{PLATFORM_ORDER.map((p) => <option key={p} value={p}>{PLATFORMS[p].label}</option>)}</Select>
          <Select aria-label="Content type" value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{["post", "carousel", "text", "video", "reel", "story"].map((t) => <option key={t}>{t}</option>)}</Select>
          <Input aria-label="Search" placeholder="Search captions…" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mainOnly} onChange={(e) => setMainOnly(e.target.checked)} />Main posts only</label>
        </div>
      </Card>
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? <Empty title="No content matches">Give the agent a campaign goal, or create a post.</Empty> : view === "gallery" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {data.map((i) => <ContentTile key={i.id} i={i} tz={can.tz} />)}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line bg-panel">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted"><tr><th className="px-3 py-2">Post</th><th className="pr-3">Platform</th><th className="pr-3">Type</th><th className="pr-3">Campaign</th><th className="pr-3">When</th><th className="pr-3">Status</th><th className="pr-3">Checks</th><th>v</th></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((i) => (
                <tr key={i.id} className="hover:bg-panel-2">
                  <td className="px-3 py-2"><Link href={`/content/${i.id}`} className="font-medium hover:underline">{i.title || i.caption.slice(0, 60) || `#${i.id}`}</Link>
                    <div className="flex gap-1">{i.generated_by !== "human" && <Badge>{i.generated_by.startsWith("demo") ? "demo generator" : i.generated_by}</Badge>}{i.master_id && <Badge tone="info">variant of #{i.master_id}</Badge>}<SyntheticBadge show={i.is_synthetic} /></div></td>
                  <td className="pr-3"><PlatformChip platform={i.platform} withLabel /></td>
                  <td className="pr-3">{i.content_type}</td>
                  <td className="pr-3 text-muted">{i.campaign_name || "—"}</td>
                  <td className="pr-3 whitespace-nowrap text-muted">{fmtDate(i.published_at || i.scheduled_at || i.planned_at, can.tz)}</td>
                  <td className="pr-3"><ContentStatusBadge status={i.status} /></td>
                  <td className="pr-3">{i.validation ? (i.validation.ok ? <Badge tone="ok">pass</Badge> : <Badge tone="bad">{i.validation.failures} fail</Badge>) : <span className="text-muted">—</span>}</td>
                  <td className="text-muted">{i.version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
