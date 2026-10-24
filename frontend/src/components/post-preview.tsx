"use client";

import { Bookmark, ChevronLeft, ChevronRight, Heart, MessageCircle, Repeat2, Send, Share2, ThumbsUp } from "lucide-react";
import { useState } from "react";
import type { Asset } from "@/lib/types";
import { cx } from "@/lib/format";

/** Visual previews per platform. Purely visual: the text shown is exactly what would be posted. */

interface PreviewProps {
  assets: Asset[];
  caption: string;
  account: string;
  type: string;
  title?: string;
  limit?: number;
}

function Avatar({ name, className }: { name: string; className?: string }) {
  return <span className={cx("grid shrink-0 place-items-center rounded-full bg-accent font-bold text-accent-ink", className || "h-8 w-8 text-xs")}>{(name || "?").slice(0, 1).toUpperCase()}</span>;
}

function Img({ a, className }: { a?: Asset; className?: string }) {
  if (!a) return <div className={cx("grid place-items-center bg-panel-2 p-6 text-center text-sm text-muted", className)}>No image attached</div>;
  return (
    <div className={cx("relative bg-panel-2", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={a.url} alt={a.alt_text || "post image"} className="h-full w-full object-cover" loading="lazy" />
      {a.placeholder && <span className="absolute left-2 top-2 rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold text-white">PLACEHOLDER</span>}
    </div>
  );
}

function Counter({ text, limit }: { text: string; limit?: number }) {
  if (!limit) return null;
  const over = text.length > limit;
  return <div className={cx("px-3 pb-2 text-[11px]", over ? "font-semibold text-bad" : "text-muted")}>{text.length}/{limit.toLocaleString("en-IN")} characters</div>;
}

function Clamp({ text, lines = 3, className }: { text: string; lines?: number; className?: string }) {
  const [more, setMore] = useState(false);
  const long = text.split("\n").length > lines || text.length > lines * 90;
  return (
    <div className={className}>
      <p className={cx("whitespace-pre-wrap", !more && long && (lines === 2 ? "line-clamp-2" : lines === 4 ? "line-clamp-4" : "line-clamp-3"))}>{text || <span className="text-muted">No caption yet.</span>}</p>
      {long && <button onClick={() => setMore(!more)} className="text-xs font-semibold text-muted hover:text-ink">{more ? "less" : "…more"}</button>}
    </div>
  );
}

export function InstagramPreview({ assets, caption, account, type, limit = 2200 }: PreviewProps) {
  const [i, setI] = useState(0);
  const n = assets.length;
  const a = assets[Math.min(i, Math.max(n - 1, 0))];
  const handle = account.toLowerCase().replace(/[^a-z0-9_.]/g, "");
  return (
    <div className="mx-auto w-full max-w-sm overflow-hidden rounded-xl border border-line bg-panel text-ink">
      <div className="flex items-center gap-2 px-3 py-2 text-sm font-semibold"><Avatar name={account} />{handle}</div>
      <div className="relative">
        <Img a={a} className="aspect-[4/5]" />
        {type === "carousel" && n > 1 && (
          <>
            <span className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-semibold text-white">{i + 1}/{n}</span>
            {i > 0 && <button aria-label="Previous slide" onClick={() => setI(i - 1)} className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-white/80 p-1 text-black"><ChevronLeft className="h-4 w-4" /></button>}
            {i < n - 1 && <button aria-label="Next slide" onClick={() => setI(i + 1)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/80 p-1 text-black"><ChevronRight className="h-4 w-4" /></button>}
            <div className="absolute inset-x-0 bottom-2 flex justify-center gap-1">
              {assets.map((_, j) => <button key={j} aria-label={`Slide ${j + 1}`} onClick={() => setI(j)} className={cx("h-1.5 w-1.5 rounded-full", j === i ? "bg-white" : "bg-white/50")} />)}
            </div>
          </>
        )}
      </div>
      <div className="flex items-center gap-3 px-3 pt-2 text-ink" aria-hidden><Heart className="h-5 w-5" /><MessageCircle className="h-5 w-5" /><Send className="h-5 w-5" /><Bookmark className="ml-auto h-5 w-5" /></div>
      <Clamp className="px-3 py-1.5 text-[13px] leading-relaxed" text={`${handle} ${caption}`} lines={3} />
      <Counter text={caption} limit={limit} />
    </div>
  );
}

export function FacebookPreview({ assets, caption, account, limit }: PreviewProps) {
  const shown = assets.slice(0, 4);
  return (
    <div className="mx-auto w-full max-w-md overflow-hidden rounded-xl border border-line bg-panel text-ink">
      <div className="flex items-center gap-2 px-3 py-2"><Avatar name={account} className="h-9 w-9 text-sm" />
        <div><div className="text-sm font-semibold">{account}</div><div className="text-[11px] text-muted">Just now · Public</div></div></div>
      <Clamp className="px-3 pb-2 text-sm" text={caption} lines={4} />
      {shown.length <= 1 ? <Img a={shown[0]} className="aspect-[4/5]" /> : (
        <div className="grid grid-cols-2 gap-0.5">
          {shown.map((a, j) => (
            <div key={a.id} className="relative"><Img a={a} className="aspect-square" />
              {j === 3 && assets.length > 4 && <span className="absolute inset-0 grid place-items-center bg-black/50 text-2xl font-bold text-white">+{assets.length - 4}</span>}</div>
          ))}
        </div>
      )}
      <div className="flex justify-around border-t border-line py-2 text-xs font-semibold text-muted" aria-hidden><span className="flex items-center gap-1"><ThumbsUp className="h-4 w-4" />Like</span><span className="flex items-center gap-1"><MessageCircle className="h-4 w-4" />Comment</span><span className="flex items-center gap-1"><Share2 className="h-4 w-4" />Share</span></div>
      <Counter text={caption} limit={limit} />
    </div>
  );
}

export function PinterestPreview({ assets, caption, account, title, limit }: PreviewProps) {
  return (
    <div className="mx-auto w-full max-w-[260px] text-ink">
      <div className="relative overflow-hidden rounded-2xl">
        <Img a={assets[0]} className="aspect-[2/3]" />
        <span className="absolute right-2 top-2 rounded-full bg-[#E60023] px-3 py-1.5 text-xs font-bold text-white">Save</span>
      </div>
      <div className="px-1 pt-2">
        <div className="line-clamp-2 text-sm font-semibold">{title || caption.slice(0, 80)}</div>
        <Clamp className="mt-0.5 text-xs text-muted" text={caption} lines={2} />
        <div className="mt-1.5 flex items-center gap-1.5 text-xs"><Avatar name={account} className="h-5 w-5 text-[9px]" />{account}</div>
      </div>
      <Counter text={caption} limit={limit} />
    </div>
  );
}

export function XPreview({ assets, caption, account, limit = 280 }: PreviewProps) {
  const handle = account.toLowerCase().replace(/[^a-z0-9_]/g, "");
  const shown = assets.slice(0, 4);
  return (
    <div className="mx-auto w-full max-w-md rounded-xl border border-line bg-panel p-3 text-ink">
      <div className="flex gap-2">
        <Avatar name={account} className="h-9 w-9 text-sm" />
        <div className="min-w-0 flex-1">
          <div className="text-sm"><strong>{account}</strong> <span className="text-muted">@{handle} · now</span></div>
          <p className="whitespace-pre-wrap text-sm">{caption}</p>
          {shown.length > 0 && (
            <div className={cx("mt-2 grid gap-0.5 overflow-hidden rounded-xl border border-line", shown.length > 1 && "grid-cols-2")}>
              {shown.map((a) => <Img key={a.id} a={a} className={shown.length > 1 ? "aspect-square" : "aspect-video"} />)}
            </div>
          )}
          <div className="mt-2 flex justify-between text-muted" aria-hidden><MessageCircle className="h-4 w-4" /><Repeat2 className="h-4 w-4" /><Heart className="h-4 w-4" /><Share2 className="h-4 w-4" /></div>
        </div>
      </div>
      <Counter text={caption} limit={limit} />
    </div>
  );
}

export function LinkedInPreview({ assets, caption, account, limit }: PreviewProps) {
  return (
    <div className="mx-auto w-full max-w-md overflow-hidden rounded-xl border border-line bg-panel text-ink">
      <div className="flex items-center gap-2 px-3 py-2"><span className="grid h-10 w-10 place-items-center rounded bg-accent text-sm font-bold text-accent-ink">{account.slice(0, 1)}</span>
        <div><div className="text-sm font-semibold">{account}</div><div className="text-[11px] text-muted">Company page · now</div></div></div>
      <Clamp className="px-3 pb-2 text-sm" text={caption} lines={3} />
      {assets[0] && <Img a={assets[0]} className="aspect-square" />}
      <div className="flex justify-around border-t border-line py-2 text-xs font-semibold text-muted" aria-hidden><span className="flex items-center gap-1"><ThumbsUp className="h-4 w-4" />Like</span><span className="flex items-center gap-1"><MessageCircle className="h-4 w-4" />Comment</span><span className="flex items-center gap-1"><Repeat2 className="h-4 w-4" />Repost</span><span className="flex items-center gap-1"><Send className="h-4 w-4" />Send</span></div>
      <Counter text={caption} limit={limit} />
    </div>
  );
}

export function ThreadsPreview({ assets, caption, account, limit = 500 }: PreviewProps) {
  const handle = account.toLowerCase().replace(/[^a-z0-9_.]/g, "");
  return (
    <div className="mx-auto w-full max-w-md rounded-xl border border-line bg-panel p-3 text-ink">
      <div className="flex gap-2">
        <div className="flex flex-col items-center"><Avatar name={account} /><span className="mt-1 w-px flex-1 bg-line" /></div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{handle} <span className="font-normal text-muted">· now</span></div>
          <p className="whitespace-pre-wrap text-sm">{caption}</p>
          {assets.length > 0 && (
            <div className="mt-2 flex gap-1.5 overflow-x-auto">
              {assets.slice(0, 6).map((a) => <Img key={a.id} a={a} className="aspect-[4/5] w-40 shrink-0 overflow-hidden rounded-lg" />)}
            </div>
          )}
          <div className="mt-2 flex gap-4 text-muted" aria-hidden><Heart className="h-4 w-4" /><MessageCircle className="h-4 w-4" /><Repeat2 className="h-4 w-4" /><Send className="h-4 w-4" /></div>
        </div>
      </div>
      <Counter text={caption} limit={limit} />
    </div>
  );
}

export function YouTubeBrief({ caption, title }: PreviewProps) {
  return (
    <div className="mx-auto w-full max-w-[240px] text-ink">
      <div className="grid aspect-[9/16] place-items-center rounded-xl border-2 border-dashed border-line bg-panel-2 p-4 text-center">
        <div><div className="text-sm font-bold">Shorts brief</div><div className="mt-1 text-xs text-muted">YouTube publishes video only. GrowthPilot doesn&apos;t make video, so this is a brief to film — it can&apos;t be published from here.</div></div>
      </div>
      {title && <div className="mt-2 text-sm font-semibold">{title}</div>}
      <p className="mt-1 whitespace-pre-wrap text-xs text-muted">{caption}</p>
    </div>
  );
}

export function PlatformPreview({ platform, ...props }: PreviewProps & { platform: string }) {
  switch (platform) {
    case "facebook": return <FacebookPreview {...props} />;
    case "pinterest": return <PinterestPreview {...props} />;
    case "x": return <XPreview {...props} />;
    case "linkedin": return <LinkedInPreview {...props} />;
    case "threads": return <ThreadsPreview {...props} />;
    case "youtube": return <YouTubeBrief {...props} />;
    default: return <InstagramPreview {...props} />;
  }
}

/** Back-compat: the original Instagram-style preview. */
export function PostPreview(props: PreviewProps) {
  return <InstagramPreview {...props} />;
}
