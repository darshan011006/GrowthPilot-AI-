"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, CalendarClock, CheckCircle2, Megaphone, Sparkles } from "lucide-react";
import { useAuth, useCan } from "@/components/auth";
import { ContentStatusBadge, Money, RunStatusBadge, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, ChangeBadge, Empty, LinkButton, Loading, Stat, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtNum, fmtPct, fmtRelative } from "@/lib/format";
import { periodMetrics } from "@/lib/period-metrics";
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
  const analytics = useApi<import("@/lib/types").Analytics>("/api/analytics");
  const { state } = useAuth();
  const can = useCan();
  const seed = useAction();
  const [seeded, setSeeded] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;

  const c = data.counts;
  const perf = data.performance;
  const periods = analytics.data ? periodMetrics(analytics.data.items) : null;
  const synthetic = perf.data_source === "synthetic" || perf.data_source === "mixed";
  const pending = (c.in_review ?? 0) + data.pending_requests;
  const loadDemo = async (brand: "poojaloka" | "aranya") => {
    if (!confirm(`Load the ${brand === "poojaloka" ? "Poojaloka" : "fictional Aranya Living"} demo? This replaces this workspace's marketing data.`)) return;
    const result = await seed.run(() => api.post("/api/demo/reset", { confirm: "RESET", brand }));
    if (result) { setSeeded(true); reload(); }
  };

  return <div className="space-y-6">
    <h1 className="sr-only">Overview</h1>
    <section className="flex flex-wrap items-center justify-between gap-5 rounded-[28px] border border-line bg-panel px-6 py-7 md:px-8 md:py-9">
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-[.2em] text-muted">{new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date())}</p>
        <h1 className="text-3xl font-bold tracking-tight md:text-4xl">Good to see you, {state?.user?.name?.split(" ")[0] || "there"}.</h1>
        <p className="mt-2 max-w-2xl text-base text-muted">{data.brand ? <><span className="text-ink">{data.brand.name}</span> workspace · {pending} {pending === 1 ? "item needs" : "items need"} your review.</> : "Your workspace growth pulse and the work that needs your attention."}{data.brand && <span className="ml-2"><SyntheticBadge show={data.brand.is_synthetic} label="Fictional brand" /></span>}</p>
      </div>
      <LinkButton href="/agent" variant="primary" className="rounded-2xl px-5 py-3.5 text-base"><Sparkles className="h-5 w-5" /> Open AI Workspace</LinkButton>
    </section>

    {data.brand && <div className="-mt-3 flex flex-wrap items-center gap-2 px-1 text-xs text-muted">
      <span className="flex gap-1">{data.brand.colors.slice(0, 5).map((color) => <span key={color} className="h-4 w-4 rounded-full border border-line" style={{ background: color }} />)}</span>
      {data.brand.catalogue && <Badge tone={data.brand.catalogue.includes("snapshot") ? "demo" : "ok"}>{data.brand.catalogue}</Badge>}
      <Link href="/brand" className="ml-auto text-accent hover:underline">Brand Brain <ArrowUpRight className="inline h-3.5 w-3.5" /></Link>
    </div>}
    {!data.has_brand && data.mode === "demo" && can.own && <Card title="Start with a demo brand" className="rounded-3xl p-6"><p className="mb-3 text-sm text-muted"><strong>Poojaloka</strong> (recommended): a Bengaluru pooja-essentials store from a dated catalogue snapshot, with clearly labelled synthetic metrics. <strong>Aranya Living</strong>: a fictional furniture brand.</p>{seed.error && <Alert tone="bad">{seed.error}</Alert>}<div className="flex flex-wrap gap-2"><Button variant="primary" busy={seed.busy} onClick={() => loadDemo("poojaloka")}>Load Poojaloka demo</Button><Button busy={seed.busy} onClick={() => loadDemo("aranya")}>Load Aranya demo</Button></div></Card>}
    {seeded && <Alert tone="ok">Demo data loaded. Your workspace is ready.</Alert>}

    <section aria-label="Workspace performance" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <Stat label="Total reach · 30d" value={fmtNum(periods?.hasData ? periods.current.reach : perf.totals.reach as number | null)} hint={<span className="flex flex-wrap items-center gap-1.5"><ChangeBadge percent={periods?.change.reach.percent ?? null} isNew={periods?.change.reach.isNew} />{synthetic && <SyntheticBadge />}</span>} />
      <Stat label="Engagement rate · 30d" value={fmtPct(periods?.hasData ? periods.current.engagement : perf.totals.engagement_rate_by_reach as number | null)} hint={<span className="flex flex-wrap items-center gap-1.5"><ChangeBadge percent={periods?.change.engagement.percent ?? null} isNew={periods?.change.engagement.isNew} />Interactions ÷ reach</span>} />
      <Stat label="Followers gained" value="—" hint="Not available from connected analytics sources" />
      <Stat label="Posts with metrics · 30d" value={periods?.hasData ? periods.current.posts : perf.with_metrics} hint={<ChangeBadge percent={periods?.change.posts.percent ?? null} isNew={periods?.change.posts.isNew} />} />
    </section>
    <section aria-label="Additional performance metrics" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <div className="xl:col-start-1"><Stat label="Interactions · 30d" value={fmtNum(periods?.hasData ? periods.current.interactions : perf.totals.interactions as number | null)} hint={<ChangeBadge percent={periods?.change.interactions.percent ?? null} isNew={periods?.change.interactions.isNew} />} /></div>
      <div className="xl:col-start-3"><Stat label="Saves · 30d" value={fmtNum(periods?.hasData ? periods.current.saves : perf.totals.saves as number | null)} hint={<ChangeBadge percent={periods?.change.saves.percent ?? null} isNew={periods?.change.saves.isNew} />} /></div>
    </section>

    <section className="grid gap-5 2xl:grid-cols-[1.55fr_1fr]">
      <Card title={<span className="flex items-center gap-2"><CalendarClock className="h-5 w-5 text-accent" /> Today&apos;s schedule</span>} actions={<LinkButton href="/calendar" variant="ghost" size="sm">View calendar <ArrowUpRight className="h-3.5 w-3.5" /></LinkButton>} className="rounded-3xl p-6">
        {data.upcoming.length ? <ul className="space-y-3">{data.upcoming.slice(0, 5).map((item) => <li key={item.id}><Link href={`/content/${item.id}`} className="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-[#0b120e] p-3.5 hover:border-accent/40"><span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-panel-2 text-xs font-semibold text-accent">{item.scheduled_at ? new Date(item.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Draft"}</span><span className="min-w-[140px] flex-1"><span className="block line-clamp-1 text-sm font-semibold text-ink">{item.title || item.caption.slice(0, 60)}</span><span className="mt-1 block text-xs text-muted">{fmtDate(item.scheduled_at, can.tz)} · {item.connection_name}</span></span><ContentStatusBadge status={item.status} /></Link></li>)}</ul> : <Empty title="Nothing on the schedule yet">Create content in AI Workspace or add a post to your calendar.</Empty>}
      </Card>
      <div className="grid gap-5 md:grid-cols-2 2xl:grid-cols-1">
        <Card title={<span className="flex items-center gap-2"><Megaphone className="h-5 w-5 text-chart-2" /> Campaigns</span>} className="rounded-3xl p-6">
          <div className="text-3xl font-bold">{data.active_campaigns.length}<span className="ml-2 text-base font-normal text-muted">active campaigns</span></div>
          <div className="mt-4 space-y-2">{data.active_campaigns.slice(0, 3).map((campaign) => <Link key={campaign.id} href={`/campaigns/${campaign.id}`} className="flex items-center justify-between rounded-xl border border-line px-3 py-2.5 text-sm hover:border-accent/40"><span className="truncate font-medium">{campaign.name}</span><Badge tone="accent">{campaign.status}</Badge></Link>)}</div>
          <Link href="/campaigns" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-accent">Manage campaigns <ArrowUpRight className="h-4 w-4" /></Link>
        </Card>
        <Card title={<span className="flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-ok" /> Approvals</span>} className="rounded-3xl p-6">
          <div className="text-3xl font-bold">{pending}<span className="ml-2 text-base font-normal text-muted">{pending === 1 ? "item needs" : "items need"} your review</span></div>
          <p className="mt-2 text-sm text-muted">Content approval and workspace decisions stay in your hands.</p>
          <Link href="/approvals" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-accent">Open approval center <ArrowUpRight className="h-4 w-4" /></Link>
        </Card>
      </div>
    </section>

    <Card title="AI team activity" subtitle="Recent runs from this workspace" actions={<LinkButton href="/agent" size="sm">Open AI Workspace</LinkButton>} className="rounded-3xl p-6">
      {data.runs.length ? <ul className="divide-y divide-line">{data.runs.slice(0, 5).map((run) => <li key={run.id} className="flex flex-wrap items-center gap-3 py-3"><span className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-panel-2 text-xs font-bold text-accent">AI</span><span className="min-w-[160px] flex-1"><Link href={`/agent/${run.id}`} className="line-clamp-1 text-sm font-medium hover:text-accent">{run.goal}</Link>{run.outcome_summary && <span className="mt-1 block line-clamp-1 text-xs text-muted">{run.outcome_summary}</span>}</span><RunStatusBadge status={run.status} /><span className="text-xs text-muted">{fmtRelative(run.created_at)}</span></li>)}</ul> : <Empty title="No agent activity yet">Start a workflow when you are ready.</Empty>}
    </Card>

    {(data.failed.length > 0 || data.next_actions.length > 0) && <section className="grid gap-5 lg:grid-cols-2">
      {data.failed.length > 0 && <Card title="Needs attention" className="rounded-3xl p-6"><ul className="space-y-3">{data.failed.map((item) => <li key={item.id}><Link href={`/content/${item.id}`} className="font-medium hover:text-accent">{item.title}</Link> <ContentStatusBadge status={item.status} /><div className="mt-1 text-xs text-bad">{item.last_error}</div></li>)}</ul></Card>}
      {data.next_actions.length > 0 && <Card title="Next steps" className="rounded-3xl p-6"><ul className="space-y-2">{data.next_actions.map((action) => <li key={action.label}><Link href={action.href} className="text-sm font-medium text-accent hover:underline">{action.label} →</Link></li>)}</ul></Card>}
    </section>}
    <footer className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-muted"><span>AI & tool cost this month: <Money usd={data.usage.month_cost_usd} digits={2} /> / ${data.usage.monthly_budget_usd.toFixed(2)} budget <Link href="/usage" className="text-accent">View usage →</Link></span><span>Performance source: {perf.data_source}{perf.freshness ? ` · updated ${fmtRelative(perf.freshness)}` : ""}</span></footer>
  </div>;
}
