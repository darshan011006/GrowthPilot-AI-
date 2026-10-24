"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useCan } from "@/components/auth";
import { PLATFORM_ORDER, PLATFORMS, PlatformChip, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Card, Empty, KeyValue, Loading, Modal, PageHeader, Select, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Asset } from "@/lib/types";

const SOURCES: [string, string][] = [
  ["rendered", "Rendered posters"], ["catalogue", "Store product photos"], ["upload", "Uploads"],
  ["ai_background", "AI backgrounds"], ["placeholder", "Placeholders"], ["", "Everything"],
];

function Detail({ id, onClose }: { id: number; onClose: () => void }) {
  const can = useCan();
  const { data: a, loading, error } = useApi<Asset>(`/api/assets/${id}`);
  return (
    <Modal open onClose={onClose} title={a?.filename || "Asset"} wide>
      {loading && !a ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : a && (
        <div className="grid gap-4 md:grid-cols-[260px_minmax(0,1fr)]">
          <div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={a.url} alt={a.alt_text || a.filename} className="w-full rounded-lg border border-line bg-panel-2" />
            <div className="mt-2 flex gap-2">
              <a className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-xs font-semibold hover:bg-panel-2" href={`${a.url}?format=png&download=1`}><Download className="h-3.5 w-3.5" />PNG</a>
              <a className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-xs font-semibold hover:bg-panel-2" href={`${a.url}?format=jpg&download=1`}><Download className="h-3.5 w-3.5" />JPG</a>
            </div>
          </div>
          <div className="min-w-0 space-y-3 text-sm">
            <KeyValue items={[
              ["Provenance", a.source_label], ["Size", `${a.width}×${a.height} · ${a.content_type} · ${Math.round((a.size_bytes || 0) / 1024)} KB`],
              ["Platform", a.meta?.platform ? <PlatformChip key="p" platform={a.meta.platform} withLabel /> : "—"],
              ["Template", a.meta?.template?.replace(/_/g, " ") || "—"],
              ["Product image", a.meta?.photo_kind === "product_photo" ? "Real product photo from the catalogue" : a.meta?.photo_kind ? "None used (typographic product card)" : "—"],
              ["Background", a.meta?.background === "ai_generated" ? "AI-generated (labelled on the image)" : a.meta?.background ? "Brand template (no AI)" : "—"],
              ["Used by", a.meta?.content_id ? <Link key="c" className="text-accent hover:underline" href={`/content/${a.meta.content_id}`}>post #{a.meta.content_id} v{a.meta.content_version}</Link> : "—"],
              ["Origin", a.origin_url ? <a key="o" className="break-all text-info hover:underline" href={a.origin_url} target="_blank" rel="noopener noreferrer">{a.origin_url}</a> : "—"],
              ["SHA-256", <code key="s" className="break-all text-[11px]">{a.sha256 || "—"}</code>],
              ["Created", fmtDate(a.created_at, can.tz)],
            ]} />
            {a.meta?.checks && (
              <div><div className="mb-1 text-xs font-semibold uppercase text-muted">Image checks</div>
                <ul className="space-y-0.5 text-xs">{a.meta.checks.map((c, i) => <li key={i} className={c.status === "fail" ? "text-bad" : c.status === "warn" ? "text-warn" : "text-ok"}>{c.status === "pass" ? "✓" : c.status === "warn" ? "!" : "✕"} {c.message}</li>)}</ul></div>
            )}
            {a.meta?.layers && (
              <div><div className="mb-1 text-xs font-semibold uppercase text-muted">Text on the image (from validated content)</div>
                <ul className="space-y-0.5 text-xs">{a.meta.layers.map((l, i) => <li key={i}><Badge>{l.kind}</Badge> {l.text} {l.contrast !== null && <span className="text-muted">· contrast {l.contrast}:1</span>}</li>)}</ul></div>
            )}
            {(a.meta?.notes || []).map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
          </div>
        </div>
      )}
    </Modal>
  );
}

function AssetsInner() {
  const params = useSearchParams();
  const [source, setSource] = useState("rendered");
  const [platform, setPlatform] = useState("");
  const [focus, setFocus] = useState<number | null>(() => (params.get("focus") ? Number(params.get("focus")) : null));
  const qs = new URLSearchParams({ source, platform }).toString();
  const { data, loading, error, reload } = useApi<Asset[]>(`/api/assets?${qs}`);
  const up = useAction();
  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    form.append("alt_text", f.name.replace(/\.[a-z]+$/i, ""));
    const r = await up.run(() => api.upload("/api/assets", form));
    e.target.value = "";
    if (r) { setSource("upload"); reload(); }
  };
  return (
    <div>
      <PageHeader title="Asset Library" subtitle="Every image GrowthPilot rendered or stored, with where it came from and the checks it passed. Posters are composed locally from brand elements and verified facts; product imagery is always a real photo, never a stock image."
        actions={<label className="cursor-pointer rounded-lg border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">Upload a real photo<input type="file" accept="image/jpeg,image/png" className="sr-only" onChange={upload} /></label>} />
      {up.error && <div className="mb-3"><Alert tone="bad">{up.error}</Alert></div>}
      <Card className="mb-4">
        <div className="flex flex-wrap gap-3">
          <Select aria-label="Source" className="w-auto" value={source} onChange={(e) => setSource(e.target.value)}>{SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          <Select aria-label="Platform" className="w-auto" value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="">All platforms</option>{PLATFORM_ORDER.map((p) => <option key={p} value={p}>{PLATFORMS[p].label}</option>)}</Select>
          {data && <span className="self-center text-sm text-muted">{data.length} image(s)</span>}
        </div>
      </Card>
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? <Empty title="No images here yet">Run a campaign goal; the Creative Agent renders posters for every platform.</Empty> : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {data.map((a) => (
            <button key={a.id} onClick={() => setFocus(a.id)} className="overflow-hidden rounded-xl border border-line bg-panel text-left transition hover:shadow-md">
              <div className="relative bg-panel-2" style={{ aspectRatio: a.width && a.height ? `${a.width}/${a.height}` : "4/5" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={a.url} alt={a.alt_text || a.filename} className="h-full w-full object-cover" loading="lazy" />
              </div>
              <div className="space-y-1 p-2 text-[11px]">
                <div className="flex items-center gap-1 truncate font-semibold">{a.platform && <PlatformChip platform={a.platform} />}{a.template?.replace(/_/g, " ") || a.filename}</div>
                <div className="flex flex-wrap gap-1"><Badge tone={a.source === "catalogue" ? "ok" : a.source === "placeholder" ? "demo" : "neutral"}>{a.source_label}</Badge>
                  {a.checks_ok === false && <Badge tone="bad">check failed</Badge>}{a.background === "ai_generated" && <Badge tone="warn">AI bg</Badge>}<SyntheticBadge show={a.is_synthetic} label="Demo" /></div>
                <div className="text-muted">{a.width}×{a.height}</div>
              </div>
            </button>
          ))}
        </div>
      )}
      {focus !== null && <Detail id={focus} onClose={() => setFocus(null)} />}
    </div>
  );
}

export default function AssetsPage() {
  return <Suspense fallback={<Loading />}><AssetsInner /></Suspense>;
}
