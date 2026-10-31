"use client";

import Link from "next/link";
import { ContentStatusBadge, PlatformChip, SyntheticBadge } from "@/components/domain";
import { Badge } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import type { ContentItem } from "@/lib/types";

export function ContentTile({ i, tz }: { i: ContentItem; tz: string }) {
  return (
    <Link href={`/content/${i.id}`} className="group overflow-hidden rounded-2xl border border-line bg-panel transition hover:border-accent/40 hover:shadow-[0_12px_40px_rgba(0,0,0,.2)]">
      <div className="relative aspect-[4/3] bg-panel-2">
        {i.asset_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={i.asset_url} alt={i.title} className="h-full w-full object-cover transition group-hover:scale-[1.02]" loading="lazy" />
        ) : (
          <div className="grid h-full place-items-center p-4 text-center text-xs text-muted">{i.content_type === "video" ? "Video brief — no image" : "No image yet"}</div>
        )}
        {i.content_type === "carousel" && <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 text-[10px] font-semibold text-white">{1 + (i.slide_asset_ids?.length || 0)} slides</span>}
      </div>
      <div className="space-y-2.5 p-4">
        <div className="line-clamp-2 min-h-10 text-sm font-semibold text-ink">{i.hook || i.title || `#${i.id}`}</div>
        <div className="flex flex-wrap items-center gap-1"><PlatformChip platform={i.platform} /><ContentStatusBadge status={i.status} />{i.master_id && <Badge tone="info">variant</Badge>}<SyntheticBadge show={i.is_synthetic} label="Demo" /></div>
        <div className="text-[11px] text-muted">{fmtDate(i.published_at || i.scheduled_at || i.planned_at, tz)}{i.campaign_name && ` · ${i.campaign_name}`}</div>
      </div>
    </Link>
  );
}

