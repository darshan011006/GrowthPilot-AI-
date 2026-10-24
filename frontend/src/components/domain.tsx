"use client";

import { Badge } from "@/components/ui";
import type { Check, ContentStatus, Finding, Validation } from "@/lib/types";
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
