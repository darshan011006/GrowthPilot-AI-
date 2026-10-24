"use client";

import { useState } from "react";
import type { Asset } from "@/lib/types";

/** Instagram-style preview. Purely visual; the caption shown is exactly what would be posted. */
export function PostPreview({ assets, caption, account, type }: { assets: Asset[]; caption: string; account: string; type: string }) {
  const [i, setI] = useState(0);
  const a = assets[Math.min(i, Math.max(assets.length - 1, 0))];
  return (
    <div className="mx-auto w-full max-w-sm overflow-hidden rounded-xl border border-line bg-panel">
      <div className="flex items-center gap-2 px-3 py-2 text-sm font-semibold"><span className="h-7 w-7 rounded-full bg-accent" />{account}</div>
      <div className="relative aspect-[4/5] bg-panel-2">
        {a ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={a.url} alt={a.alt_text || "post image"} className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center p-6 text-center text-sm text-muted">No image attached</div>
        )}
        {a?.placeholder && <span className="absolute left-2 top-2 rounded bg-black/70 px-2 py-0.5 text-[10px] font-bold text-white">PLACEHOLDER</span>}
        {type === "carousel" && assets.length > 1 && (
          <div className="absolute inset-x-0 bottom-2 flex justify-center gap-1">
            {assets.map((_, j) => (
              <button key={j} aria-label={`Slide ${j + 1}`} onClick={() => setI(j)} className={`h-1.5 w-1.5 rounded-full ${j === i ? "bg-white" : "bg-white/50"}`} />
            ))}
          </div>
        )}
      </div>
      <p className="whitespace-pre-wrap px-3 py-2 text-[13px] leading-relaxed"><strong>{account}</strong> {caption || <span className="text-muted">No caption yet.</span>}</p>
      <div className="px-3 pb-2 text-[11px] text-muted">{caption.length}/2200 characters</div>
    </div>
  );
}
