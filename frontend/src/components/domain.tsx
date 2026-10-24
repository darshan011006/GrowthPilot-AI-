"use client";

import { Badge } from "@/components/ui";
import type { Check, ContentStatus, Finding, Freshness, RoleKey, Validation } from "@/lib/types";
import { cx } from "@/lib/format";

const CONTENT: Record<ContentStatus, [string, Parameters<typeof Badge>[0]["tone"]]> = {
  draft: ["Draft", "neutral"],
  in_review: ["In review", "warn"],
  changes_requested: ["Changes requested", "bad"],
  approved: ["Approved", "accent"],
  scheduled: ["Scheduled", "info"],
  publishing: ["Publishing", "info"],
  published: ["Published", "ok"],
  failed: ["Failed", "bad"],
  cancelled: ["Cancelled", "neutral"],
};

export function ContentStatusBadge({ status }: { status: ContentStatus }) {
  const [label, tone] = CONTENT[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{label}</Badge>;
}

const RUN: Record<string, [string, Parameters<typeof Badge>[0]["tone"]]> = {
  queued: ["Queued", "neutral"],
  running: ["Running", "info"],
  paused: ["Paused", "warn"],
  awaiting_approval: ["Awaiting approval", "warn"],
  completed: ["Completed", "ok"],
  blocked: ["Blocked", "bad"],
  failed: ["Failed", "bad"],
  cancelled: ["Cancelled", "neutral"],
};

export function RunStatusBadge({ status }: { status: string }) {
  const [label, tone] = RUN[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{label}</Badge>;
}

const EVIDENCE: Record<Finding["classification"], [string, Parameters<typeof Badge>[0]["tone"], string]> = {
  verified_observation: ["Verified observation", "ok", "We observed this directly (e.g. fetched page content or our own data)."],
  source_reported: ["Source-reported", "info", "A source says this; GrowthPilot has not independently verified it."],
  inference: ["Inference", "warm", "Derived by reasoning from other evidence."],
  hypothesis: ["Hypothesis", "accent", "Proposed and untested."],
  unknown: ["Unknown", "neutral", "Not available through connected sources."],
};

export function EvidenceBadge({ c }: { c: Finding["classification"] }) {
  const [label, tone, title] = EVIDENCE[c] ?? [c, "neutral", ""];
  return <Badge tone={tone} title={title}>{label}</Badge>;
}

export function SyntheticBadge({ show = true, label = "Synthetic" }: { show?: boolean; label?: string }) {
  if (!show) return null;
  return <Badge tone="demo" title="Demo fixture or synthetic data — not real business data.">{label}</Badge>;
}

export function MockBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return <Badge tone="demo" title="This step used a mock adapter or labelled fixture data.">Mock / fixture</Badge>;
}

const CONN: Record<string, [string, Parameters<typeof Badge>[0]["tone"]]> = {
  not_configured: ["Not configured", "neutral"],
  config_incomplete: ["Configuration incomplete", "warn"],
  configured: ["Configured (not verified)", "info"],
  awaiting_authorization: ["Awaiting authorisation", "warn"],
  awaiting_provider_approval: ["Awaiting provider approval", "warn"],
  connected: ["Connected & verified", "ok"],
  expired: ["Expired — reconnect", "bad"],
  failed: ["Failed", "bad"],
  demo: ["Demo adapter", "demo"],
  not_implemented: ["Live adapter not built yet", "neutral"],
};

export function ConnectionBadge({ status }: { status: string }) {
  const [label, tone] = CONN[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{label}</Badge>;
}

const CHECK_ICON = { pass: "✓", warn: "!", fail: "✕" } as const;
const CHECK_CLS = { pass: "text-ok", warn: "text-warn", fail: "text-bad" } as const;

function CheckList({ title, checks }: { title: string; checks: Check[] }) {
  const shown = checks.filter((c) => c.status !== "pass");
  const passes = checks.filter((c) => c.status === "pass");
  return (
    <div>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{title}</div>
      <ul className="space-y-1 text-sm">
        {shown.map((c, i) => (
          <li key={i} className="flex gap-2">
            <span className={cx("w-4 shrink-0 text-center font-bold", CHECK_CLS[c.status])} aria-label={c.status}>{CHECK_ICON[c.status]}</span>
            <span>
              {c.message}
              {c.claim && <span className="text-muted"> — “{c.claim.slice(0, 120)}”</span>}
            </span>
          </li>
        ))}
        {passes.length > 0 && (
          <li className="flex gap-2 text-muted">
            <span className="w-4 shrink-0 text-center font-bold text-ok">✓</span>
            <span title={passes.map((p) => `${p.message}${p.evidence ? ` (${p.evidence})` : ""}`).join("\n")}>{passes.length} check(s) passed</span>
          </li>
        )}
      </ul>
    </div>
  );
}

export function ValidationPanel({ v, version }: { v: Validation | null; version: number }) {
  if (!v) return <p className="text-sm text-muted">Not validated yet.</p>;
  const stale = v.version !== version;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {v.ok ? <Badge tone="ok">Passes validation</Badge> : <Badge tone="bad">{v.failures} failure(s)</Badge>}
        {v.warnings > 0 && <Badge tone="warn">{v.warnings} warning(s)</Badge>}
        {stale && <Badge tone="neutral">Checked v{v.version}; now v{version}</Badge>}
      </div>
      <CheckList title="Product claims" checks={v.product_claims} />
      <CheckList title="Brand consistency" checks={v.brand} />
      <CheckList title="Platform constraints" checks={v.platform} />
    </div>
  );
}

export function SourceLink({ f }: { f: Pick<Finding, "source_url" | "source_title" | "source_type" | "is_synthetic"> }) {
  if (f.source_url) {
    return (
      <a href={f.source_url} target="_blank" rel="noopener noreferrer nofollow" className="break-all text-info underline-offset-2 hover:underline">
        {f.source_title || f.source_url}
      </a>
    );
  }
  return <span className="text-muted">{f.source_title || f.source_type}{f.is_synthetic ? " (no real source)" : ""}</span>;
}

// ── agent roles, effects, platforms, freshness ───────────────────────────

export const ROLES: Record<RoleKey, { label: string; short: string; cls: string; dot: string }> = {
  orchestrator: { label: "Orchestrator", short: "Orchestrator", cls: "bg-panel-2 text-ink", dot: "bg-muted" },
  research: { label: "Research Agent", short: "Research", cls: "bg-info-soft text-info", dot: "bg-info" },
  strategy: { label: "Strategy Agent", short: "Strategy", cls: "bg-accent-soft text-accent", dot: "bg-accent" },
  creative: { label: "Creative Agent", short: "Creative", cls: "bg-warm-soft text-warm", dot: "bg-warm" },
  verification: { label: "Brand & Product Verification Agent", short: "Verification", cls: "bg-ok-soft text-ok", dot: "bg-ok" },
  distribution: { label: "Distribution Agent", short: "Distribution", cls: "bg-demo-soft text-demo", dot: "bg-demo" },
  analyst: { label: "Performance Analyst Agent", short: "Analyst", cls: "bg-bad-soft text-bad", dot: "bg-bad" },
};

export function RoleBadge({ role, full = false }: { role?: RoleKey | string | null; full?: boolean }) {
  const r = ROLES[(role || "orchestrator") as RoleKey] ?? ROLES.orchestrator;
  return <span title={r.label} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold", r.cls)}>
    <span className={cx("h-1.5 w-1.5 rounded-full", r.dot)} />{full ? r.label : r.short}</span>;
}

const EFFECTS: Record<string, [string, Parameters<typeof Badge>[0]["tone"], string]> = {
  read_only: ["read-only", "neutral", "Reads workspace data only."],
  local_write: ["writes locally", "info", "Creates or edits records/files in this workspace."],
  cost: ["may cost money", "warn", "May call a paid provider (LLM, search, image)."],
  external_read: ["reads 3rd party", "info", "Reads from an external service."],
  external_write: ["changes 3rd party", "bad", "Changes state at an external service."],
  public_publish: ["publishes publicly", "bad", "Posts publicly — only human-approved versions."],
};

export function EffectBadges({ effect }: { effect: string }) {
  if (!effect) return null;
  return <>{effect.split(",").filter(Boolean).map((e) => {
    const [label, tone, title] = EFFECTS[e] ?? [e, "neutral", ""];
    return <Badge key={e} tone={tone} title={title}>{label}</Badge>;
  })}</>;
}

export const PLATFORMS: Record<string, { label: string; short: string; color: string }> = {
  instagram: { label: "Instagram", short: "IG", color: "#C13584" },
  facebook: { label: "Facebook", short: "FB", color: "#1877F2" },
  pinterest: { label: "Pinterest", short: "Pin", color: "#E60023" },
  x: { label: "X", short: "X", color: "#111111" },
  linkedin: { label: "LinkedIn", short: "in", color: "#0A66C2" },
  youtube: { label: "YouTube", short: "YT", color: "#FF0000" },
  threads: { label: "Threads", short: "Th", color: "#333333" },
};
export const PLATFORM_ORDER = ["instagram", "facebook", "pinterest", "x", "linkedin", "youtube", "threads"];

export function PlatformChip({ platform, withLabel = false, className }: { platform: string; withLabel?: boolean; className?: string }) {
  const p = PLATFORMS[platform] ?? { label: platform, short: platform.slice(0, 2), color: "#666" };
  return (
    <span title={p.label} className={cx("inline-flex items-center gap-1 whitespace-nowrap text-[11px] font-semibold", className)}>
      <span className="grid h-5 min-w-5 place-items-center rounded px-1 text-[10px] font-bold text-white" style={{ background: p.color }}>{p.short}</span>
      {withLabel && <span className="text-ink">{p.label}</span>}
    </span>
  );
}

const FRESH: Record<Freshness["state"], Parameters<typeof Badge>[0]["tone"]> = { fresh: "ok", aging: "warn", stale: "bad", manual: "neutral" };

export function FreshnessBadge({ f }: { f?: Freshness | null }) {
  if (!f) return null;
  return <Badge tone={FRESH[f.state]} title={f.label}>{f.state === "manual" ? "manual entry" : f.state}{f.age_hours !== null && f.state !== "manual" ? ` · ${f.age_hours < 48 ? `${Math.round(f.age_hours)}h` : `${Math.round(f.age_hours / 24)}d`}` : ""}</Badge>;
}

const IMAGE_KIND: Record<string, [string, Parameters<typeof Badge>[0]["tone"], string]> = {
  product_photo: ["real photo", "ok", "The store's own photo of this product."],
  stock_photo: ["stock image only", "warn", "The store shows a generic stock image; GrowthPilot never uses it as the product."],
  unverified: ["image unverified", "warn", "Image host isn't the store's own uploads."],
  none: ["no image", "neutral", "No image listed."],
};

export function ImageKindBadge({ kind }: { kind: string }) {
  const [label, tone, title] = IMAGE_KIND[kind] ?? [kind, "neutral", ""];
  return <Badge tone={tone} title={title}>{label}</Badge>;
}

export function Money({ usd, digits = 4 }: { usd: number | null | undefined; digits?: number }) {
  if (usd === null || usd === undefined) return <span className="text-muted">—</span>;
  return <span title="Estimate from published provider prices">${usd.toFixed(digits)}</span>;
}
