"use client";

import Link from "next/link";
import { useState } from "react";
import { useCan } from "@/components/auth";
import { ContentStatusBadge, EvidenceBadge, Money, PlatformChip, RunStatusBadge, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, LinkButton, Loading, PageHeader, Stat, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtNum, fmtPct, fmtRelative } from "@/lib/format";
import type { Campaign, Connection, ContentItem, Experiment, Finding, Recommendation, Run } from "@/lib/types";

interface Overview {
  mode: "demo" | "live";
  counts: Record<string, number>;
  active_campaigns: Campaign[];
  upcoming: ContentItem[];
  failed: ContentItem[];
  runs: Run[];
  recommendations: Recommendation[];
  opportunities: Finding[];
  experiments: Experiment[];
  connections: Connection[];
  performance: { data_source: string; freshness: string | null; published: number; with_metrics: number; totals: Record<string, number | null> };
  next_actions: { label: string; href: string }[];
  has_brand: boolean;
  pending_requests: number;
  usage: { month_cost_usd: number; monthly_budget_usd: number };
  brand: { name: string; is_synthetic: boolean; colors: string[]; catalogue: string | null } | null;
}

export default function OverviewPage() {
  const { data, error, loading, reload } = useApi<Overview>("/api/overview");
  const can = useCan();
  const seed = useAction();
  const [seeded, setSeeded] = useState(false);

  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  const c = data.counts;
  const perf = data.performance;
  const synthetic = perf.data_source === "synthetic" || perf.data_source === "mixed";

  const loadDemo = async (brand: "poojaloka" | "aranya") => {
    if (!confirm(`Load the ${brand === "poojaloka" ? "Poojaloka" : "fictional Aranya Living"} demo? This replaces this workspace's marketing data.`)) return;
    const r = await seed.run(() => api.post("/api/demo/reset", { confirm: "RESET", brand }));
    if (r) {
      setSeeded(true);
      reload();
    }
  };

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="What the agent is working on, what needs you, and what the data says so far."
        actions={<LinkButton href="/agent" variant="primary">Give the agent a goal</LinkButton>}
      />
      {data.brand && (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel p-3">
          <span className="flex gap-1">{data.brand.colors.slice(0, 5).map((c) => <span key={c} className="h-5 w-5 rounded-full border border-line" style={{ background: c }} />)}</span>
          <span className="font-semibold">{data.brand.name}</span>
          {data.brand.catalogue && <Badge tone={data.brand.catalogue.includes("snapshot") ? "demo" : "ok"}>{data.brand.catalogue}</Badge>}
          <SyntheticBadge show={data.brand.is_synthetic} label="Fictional brand" />
          <Link href="/brand" className="ml-auto text-sm text-accent hover:underline">Brand Brain →</Link>
        </div>
      )}
      {!data.has_brand && data.mode === "demo" && can.own && (
        <Card className="mb-5" title="Start with a demo brand">
          <p className="mb-3 text-sm text-muted"><strong>Poojaloka</strong> (recommended): the real catalogue of a Bengaluru pooja-essentials store from a dated snapshot, its own festival guides, plus clearly labelled fictional competitors and synthetic metrics. <strong>Aranya Living</strong>: a fictional furniture brand used by the regression tests.</p>
          {seed.error && <Alert tone="bad">{seed.error}</Alert>}
          <div className="flex flex-wrap gap-2"><Button variant="primary" busy={seed.busy} onClick={() => loadDemo("poojaloka")}>Load Poojaloka demo</Button><Button busy={seed.busy} onClick={() => loadDemo("aranya")}>Load Aranya (fictional)</Button></div>
        </Card>
      )}
      {seeded && <div className="mb-4"><Alert tone="ok">Demo data loaded. Try the Agent Command Centre next.</Alert></div>}

      {data.next_actions.length > 0 && (
        <Card className="mb-5" title="Recommended next actions">
          <ul className="space-y-1.5 text-sm">
            {data.next_actions.map((a) => (
              <li key={a.label}><Link href={a.href} className="font-medium text-accent hover:underline">→ {a.label}</Link></li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Active campaigns" value={data.active_campaigns.length} />
        <Stat label="Pending approval" value={(c.in_review ?? 0) + data.pending_requests} tone={c.in_review || data.pending_requests ? "warn" : undefined} hint={data.pending_requests ? `${data.pending_requests} budget/strategy decision(s)` : undefined} />
        <Stat label="Scheduled" value={c.scheduled ?? 0} />
        <Stat label="Published" value={c.published ?? 0} />
        <Stat label="Engagement rate" value={fmtPct(perf.totals.engagement_rate_by_reach as number | null)}
          hint={<>{perf.with_metrics} post(s) with metrics {synthetic && <SyntheticBadge />}</>} />
        <Stat label="AI & tool cost (month)" value={<Money usd={data.usage.month_cost_usd} digits={2} />} hint={<Link href="/usage" className="hover:underline">of ${data.usage.monthly_budget_usd.toFixed(2)} budget →</Link>} />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Recent agent runs" actions={<LinkButton href="/agent" size="sm">All runs</LinkButton>}>
          {data.runs.length === 0 ? <Empty title="No runs yet">Ask the agent to plan a campaign or evaluate results.</Empty> : (
            <ul className="divide-y divide-line">
              {data.runs.map((r) => (
                <li key={r.id} className="py-2.5">
                  <Link href={`/agent/${r.id}`} className="flex flex-wrap items-center justify-between gap-2 hover:underline">
                    <span className="line-clamp-1 text-sm font-medium">{r.goal}</span>
                    <span className="flex items-center gap-2 text-xs text-muted"><RunStatusBadge status={r.status} /> {fmtRelative(r.created_at)}</span>
                  </Link>
                  {r.outcome_summary && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{r.outcome_summary}</p>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Platforms" actions={<LinkButton href="/integrations" size="sm">Manage</LinkButton>}>
          {data.connections.length === 0 ? <p className="text-sm text-muted">No publishing connection yet.</p> : (
            <ul className="space-y-2 text-sm">
              {data.connections.map((x) => (
                <li key={x.id} className="flex items-center justify-between gap-2"><PlatformChip platform={x.platform} withLabel />
                  <Badge tone={x.status === "demo" ? "demo" : x.status === "connected" ? "ok" : "warn"}>{x.status === "demo" ? "simulated" : x.status}</Badge></li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Evidence-backed opportunities" subtitle="Gaps the agent found, recorded as inferences with their evidence.">
          {data.opportunities.length === 0 ? <p className="text-sm text-muted">Run a research or campaign goal to find opportunities.</p> : (
            <ul className="space-y-3 text-sm">
              {data.opportunities.map((f) => (
                <li key={f.id}>
                  <div className="mb-0.5 flex flex-wrap items-center gap-1.5"><strong>{f.topic}</strong><EvidenceBadge c={f.classification} /><SyntheticBadge show={f.is_synthetic} /></div>
                  <p className="text-muted">{f.statement}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Recommendations" actions={<LinkButton href="/experiments" size="sm">Experiments</LinkButton>}>
          {data.recommendations.length === 0 ? <p className="text-sm text-muted">Evaluate results to get recommendations.</p> : (
            <ul className="space-y-3 text-sm">
              {data.recommendations.map((r) => (
                <li key={r.id}>
                  <div className="flex flex-wrap items-center gap-1.5"><strong>{r.title}</strong><Badge tone={r.priority === "high" ? "warm" : "neutral"}>{r.priority}</Badge><SyntheticBadge show={r.is_synthetic} /></div>
                  <p className="text-muted">{r.detail}</p>
                  {r.uncertainty && <p className="text-xs text-muted">Uncertainty: {r.uncertainty}</p>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Up next" actions={<LinkButton href="/calendar" size="sm">Calendar</LinkButton>}>
          {data.upcoming.length === 0 ? <p className="text-sm text-muted">Nothing scheduled.</p> : (
            <ul className="space-y-2 text-sm">
              {data.upcoming.map((i) => (
                <li key={i.id}><Link href={`/content/${i.id}`} className="hover:underline">{i.title || i.caption.slice(0, 50)}</Link>
                  <div className="text-xs text-muted">{fmtDate(i.scheduled_at, can.tz)} · {i.connection_name}</div></li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.failed.length > 0 && (
        <Card className="mt-5" title="Needs attention">
          <ul className="space-y-2 text-sm">
            {data.failed.map((i) => (
              <li key={i.id}><Link href={`/content/${i.id}`} className="font-medium hover:underline">{i.title}</Link> <ContentStatusBadge status={i.status} /><div className="text-xs text-bad">{i.last_error}</div></li>
            ))}
          </ul>
        </Card>
      )}
      {perf.with_metrics > 0 && (
        <p className="mt-5 text-xs text-muted">
          Reach {fmtNum(perf.totals.reach as number)} · interactions {fmtNum(perf.totals.interactions as number)} · data {perf.data_source}
          {perf.freshness && ` · last collected ${fmtRelative(perf.freshness)}`}
        </p>
      )}
    </div>
  );
}
