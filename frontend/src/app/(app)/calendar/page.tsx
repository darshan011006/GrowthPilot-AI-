"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useCan } from "@/components/auth";
import { ContentStatusBadge, PLATFORM_ORDER, PLATFORMS, PlatformChip } from "@/components/domain";
import { Alert, Button, Card, Loading, PageHeader, Select, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { cx, toLocalInput } from "@/lib/format";
import type { Campaign, ContentItem } from "@/lib/types";

const MOVABLE = ["draft", "in_review", "changes_requested", "approved"];
const STATUS_BG: Record<string, string> = {
  draft: "border-line bg-panel-2", in_review: "border-warn/40 bg-warn-soft", changes_requested: "border-bad/40 bg-bad-soft",
  approved: "border-accent/40 bg-accent-soft", scheduled: "border-info/40 bg-info-soft", publishing: "border-info/40 bg-info-soft",
  published: "border-ok/40 bg-ok-soft", failed: "border-bad/40 bg-bad-soft", cancelled: "border-line bg-panel-2 opacity-60",
};

function addDays(ymd: string, n: number): string {
  const d = new Date(`${ymd}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function weekStart(ymd: string): string {
  const d = new Date(`${ymd}T12:00:00Z`);
  const dow = (d.getUTCDay() + 6) % 7; // Monday = 0
  return addDays(ymd, -dow);
}

export default function CalendarPage() {
  const can = useCan();
  const today = toLocalInput(new Date().toISOString(), can.tz).slice(0, 10);
  const [view, setView] = useState<"week" | "day">("week");
  const [anchor, setAnchor] = useState(today);
  const [campaign, setCampaign] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [platform, setPlatform] = useState("");
  const [dragOver, setDragOver] = useState<string | null>(null);
  const move = useAction();
  const start = view === "week" ? weekStart(anchor) : anchor;
  const days = view === "week" ? Array.from({ length: 7 }, (_, i) => addDays(start, i)) : [anchor];
  const end = addDays(days[days.length - 1], 1);
  const qs = new URLSearchParams({ start: `${start}T00:00`, end: `${end}T00:00`, status, content_type: type, platform, ...(campaign ? { campaign_id: campaign } : {}) }).toString();
  const { data, loading, error, reload } = useApi<{ timezone: string; items: ContentItem[] }>(`/api/calendar?${qs}`);
  const onDrop = async (day: string, e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(null);
    const [id, time] = e.dataTransfer.getData("text/plain").split("|");
    if (!id || !can.edit) return;
    if (await move.run(() => api.put(`/api/content/${id}`, { planned_at: `${day}T${time || "09:30"}`, note: "Moved on the calendar" }))) reload();
  };
  const camps = useApi<Campaign[]>("/api/campaigns");

  const byDay = useMemo(() => {
    const m: Record<string, { time: string; item: ContentItem }[]> = {};
    for (const i of data?.items || []) {
      const when = i.published_at || i.scheduled_at || i.planned_at;
      const local = toLocalInput(when, can.tz);
      const day = local.slice(0, 10);
      (m[day] ||= []).push({ time: local.slice(11, 16), item: i });
    }
    Object.values(m).forEach((v) => v.sort((a, b) => a.time.localeCompare(b.time)));
    return m;
  }, [data, can.tz]);

  const label = (ymd: string) => new Date(`${ymd}T12:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

  return (
    <div>
      <PageHeader title="Content Calendar" subtitle={`Every platform's posts in ${data?.timezone || can.tz}. Drag a draft or approved post to another day to re-plan it (approval is kept: only the time changes). Publishing runs from the backend worker.`} />
      {move.error && <div className="mb-3"><Alert tone="bad">{move.error}</Alert></div>}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setAnchor(addDays(anchor, view === "week" ? -7 : -1))} aria-label="Previous">←</Button>
          <Button size="sm" onClick={() => setAnchor(today)}>Today</Button>
          <Button size="sm" onClick={() => setAnchor(addDays(anchor, view === "week" ? 7 : 1))} aria-label="Next">→</Button>
          <span className="mx-2 text-sm font-semibold">{view === "week" ? `${label(days[0])} – ${label(days[6])}` : label(anchor)}</span>
          <div className="grid w-full grid-cols-2 gap-2 md:w-auto md:flex-1 md:grid-cols-5">
            <Select aria-label="View" value={view} onChange={(e) => setView(e.target.value as "week" | "day")}><option value="week">Week</option><option value="day">Day</option></Select>
            <Select aria-label="Campaign" value={campaign} onChange={(e) => setCampaign(e.target.value)}><option value="">All campaigns</option>{camps.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
            <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>{["draft", "in_review", "approved", "scheduled", "published", "failed", "cancelled"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
            </Select>
            <Select aria-label="Platform" value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="">All platforms</option>{PLATFORM_ORDER.map((p) => <option key={p} value={p}>{PLATFORMS[p].label}</option>)}</Select>
            <Select aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{["post", "carousel", "text", "video"].map((t) => <option key={t}>{t}</option>)}</Select>
          </div>
        </div>
      </Card>
      {error && <Alert tone="bad">{error}</Alert>}
      {loading && !data ? <Loading /> : (
        <div className={cx("grid gap-2", view === "week" ? "grid-cols-1 md:grid-cols-7" : "grid-cols-1")}>
          {days.map((d) => (
            <div key={d} onDragOver={(e) => { if (can.edit) { e.preventDefault(); setDragOver(d); } }} onDragLeave={() => setDragOver(null)} onDrop={(e) => onDrop(d, e)}
              className={cx("min-h-40 rounded-xl border bg-panel p-2 transition", d === today ? "border-accent" : "border-line", dragOver === d && "ring-2 ring-accent")}>
              <div className={cx("mb-2 text-xs font-semibold", d === today ? "text-accent" : "text-muted")}>{label(d)}</div>
              <div className="space-y-1.5">
                {(byDay[d] || []).map(({ time, item }) => (
                  <Link key={item.id} href={`/content/${item.id}`} draggable={can.edit && MOVABLE.includes(item.status)}
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", `${item.id}|${time}`)}
                    title={MOVABLE.includes(item.status) ? "Drag to another day to re-plan" : item.status === "scheduled" ? "Unschedule it to move" : undefined}
                    className={cx("block rounded-lg border px-2 py-1.5 text-xs hover:shadow-sm", STATUS_BG[item.status], can.edit && MOVABLE.includes(item.status) && "cursor-grab")}>
                    <div className="flex items-center justify-between gap-1"><span className="flex items-center gap-1 font-semibold"><PlatformChip platform={item.platform} />{time}</span><span className="text-[10px] uppercase text-muted">{item.content_type}</span></div>
                    <div className="line-clamp-2 font-medium text-ink">{item.title || item.caption.slice(0, 40)}</div>
                    {view === "day" && <div className="mt-1"><ContentStatusBadge status={item.status} /> {item.connection_name && <span className="text-muted">· {item.connection_name}</span>}</div>}
                  </Link>
                ))}
                {!(byDay[d] || []).length && <div className="text-[11px] text-muted">—</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
