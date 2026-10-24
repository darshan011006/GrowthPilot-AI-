"use client";

import { AlertTriangle, ArrowRightLeft, Brain, CheckCircle2, CircleDot, Eye, Flag, GitBranch, Hand, ListChecks, Wrench } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useCan } from "@/components/auth";
import { EffectBadges, MockBadge, Money, ROLES, RoleBadge, RunStatusBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, LinkButton, Loading, PageHeader, useAction } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cx, fmtDate, fmtNum } from "@/lib/format";
import type { ApprovalRequest, RoleKey, Run, Step } from "@/lib/types";

const PHASE: Record<Step["phase"], { icon: typeof Eye; label: string; cls: string }> = {
  observe: { icon: Eye, label: "Observe", cls: "text-info" },
  plan: { icon: ListChecks, label: "Plan", cls: "text-accent" },
  delegate: { icon: ArrowRightLeft, label: "Delegate", cls: "text-muted" },
  tool: { icon: Wrench, label: "Action", cls: "text-ink" },
  evaluate: { icon: CheckCircle2, label: "Verified", cls: "text-ok" },
  replan: { icon: GitBranch, label: "Re-plan", cls: "text-warm" },
  decision: { icon: Brain, label: "Decision", cls: "text-accent" },
  approval: { icon: Hand, label: "Approval", cls: "text-warn" },
  finish: { icon: Flag, label: "Finish", cls: "text-ok" },
  error: { icon: AlertTriangle, label: "Error", cls: "text-bad" },
};

/** Plain-language activity titles for tool steps. */
const ACTIVITY: Record<string, string> = {
  inspect_brand: "Reading the brand profile", retrieve_catalogue: "Choosing products from the catalogue",
  verify_product_facts: "Checking product facts", search_web: "Searching the web", inspect_website: "Reading a public page",
  analyse_trends: "Collecting trend and festival signals", collect_competitor_references: "Comparing public competitor content",
  analyse_campaign_history: "Learning from past results", identify_content_gaps: "Identifying content opportunities",
  create_campaign_plan: "Writing the campaign strategy", rank_campaign_ideas: "Ranking campaign hypotheses",
  estimate_campaign_cost: "Estimating cost against budget", check_platform_capabilities: "Checking platform readiness",
  prepare_schedule: "Preparing the schedule", create_content_brief: "Writing creative briefs",
  generate_caption: "Writing captions", generate_creative_asset: "Rendering poster images",
  validate_creative: "Checking brand, format and image quality", create_platform_variant: "Adapting posts for each platform",
  request_human_approval: "Asking for approval", publish_approved_content: "Publishing approved posts",
  verify_publication: "Verifying publication", retrieve_available_analytics: "Collecting available metrics",
  evaluate_experiment: "Evaluating the experiment", recommend_next_action: "Recommending the next action",
  generate_campaign_report: "Writing the report",
};

const ACTIVE = ["queued", "running"];
const ROLE_ORDER: RoleKey[] = ["research", "strategy", "creative", "verification", "distribution", "analyst"];

function Json({ v }: { v: unknown }) {
  return <pre className="max-h-72 overflow-auto rounded-lg bg-panel-2 p-2 text-[11px]">{JSON.stringify(v, null, 2)}</pre>;
}

function StepRow({ s, runId }: { s: Step; runId: string }) {
  const [open, setOpen] = useState(false);
  const meta = PHASE[s.phase] ?? PHASE.tool;
  const Icon = meta.icon;
  const tone = s.status === "error" ? "bad" : s.status === "blocked" ? "warn" : undefined;
  if (s.phase === "delegate") {
    return (
      <li className="relative pl-8 text-xs text-muted">
        <span className="absolute left-1 top-0.5 grid h-4 w-4 place-items-center rounded-full bg-panel-2"><ArrowRightLeft className="h-3 w-3" aria-hidden /></span>
        {s.message}
      </li>
    );
  }
  const role = ROLES[s.role] ?? ROLES.orchestrator;
  const title = s.phase === "tool" && s.tool ? ACTIVITY[s.tool] || s.tool : meta.label;
  const highlight = s.phase === "decision" || s.phase === "replan";
  return (
    <li className="relative pl-8">
      <span className={cx("absolute left-0 top-0.5 grid h-6 w-6 place-items-center rounded-full border-2 bg-panel", meta.cls)} style={{ borderColor: "currentColor" }}>
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </span>
      <div className={cx("rounded-lg", highlight && "border border-line bg-panel-2/60 p-2")}>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-semibold text-ink">{title}</span>
          {s.phase !== "tool" && <span className="text-muted">{meta.label}</span>}
          <RoleBadge role={s.role} />
          {s.tool && <code className="rounded bg-panel-2 px-1.5 py-0.5 text-[11px]">{s.tool}</code>}
          {tone && <Badge tone={tone}>{s.status}</Badge>}
          {s.attempt > 1 && <Badge tone="info">attempt {s.attempt}</Badge>}
          <MockBadge show={s.is_mock} />
          <span className="ml-auto flex items-center gap-2 text-muted">
            {s.cost_usd > 0 && <Money usd={s.cost_usd} />}
            {s.duration_ms > 0 && <span>{s.duration_ms} ms</span>}
            {s.tokens > 0 && <span>{fmtNum(s.tokens)} tok</span>}
            <span>#{s.seq}</span>
          </span>
        </div>
        <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink">{s.message}</p>
        {(s.input || s.output || s.evidence_ids?.length > 0) && (
          <button onClick={() => setOpen(!open)} className="mt-1 text-xs font-semibold text-info hover:underline" aria-expanded={open}>
            {open ? "Hide details" : "Details"}
          </button>
        )}
        {open && (
          <div className="mt-2 space-y-2 rounded-lg border border-line p-2 text-xs">
            <div className="flex flex-wrap items-center gap-1.5"><span className="font-semibold">Specialist:</span> {role.label}
              {s.effect && <><span className="ml-2 font-semibold">Side effects:</span> <EffectBadges effect={s.effect} /></>}</div>
            {s.evidence_ids?.length > 0 && (
              <div><span className="font-semibold">Evidence used:</span>{" "}
                {s.evidence_ids.slice(0, 20).map((id) => <Link key={id} href={`/research?run_id=${runId}`} className="mr-1 text-info hover:underline">#{id}</Link>)}
                {s.evidence_ids.length > 20 && <span className="text-muted">+{s.evidence_ids.length - 20} more</span>}</div>
            )}
            <div className="grid gap-2 md:grid-cols-2">
              {s.input && <div><div className="mb-1 font-semibold">Tool input</div><Json v={s.input} /></div>}
              {s.output && <div><div className="mb-1 font-semibold">Result</div><Json v={s.output} /></div>}
            </div>
          </div>
        )}
      </div>
    </li>
  );
}

function BudgetRequest({ id, onDone }: { id: number; onDone: () => void }) {
  const can = useCan();
  const [req, setReq] = useState<ApprovalRequest | null>(null);
  const act = useAction();
  useEffect(() => {
    api.get<ApprovalRequest[]>("/api/approval-requests?status=").then((rows) => setReq(rows.find((r) => r.id === id) || null)).catch(() => {});
  }, [id]);
  if (!req || req.status !== "pending") return null;
  const decide = async (approve: boolean) => {
    if (await act.run(() => api.post(`/api/approval-requests/${req.id}/decide`, { approve }))) onDone();
  };
  return (
    <div className="mb-4">
      <Alert tone="warn" title={req.title}>
        <p>{req.detail}</p>
        {can.own ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="ok" busy={act.busy} onClick={() => decide(true)}>Approve ${req.payload.needed_usd?.toFixed(2)}</Button>
            <Button size="sm" variant="danger" busy={act.busy} onClick={() => decide(false)}>Decline — continue without it</Button>
          </div>
        ) : <p className="mt-1 text-xs">An owner needs to decide.</p>}
        {act.error && <p className="mt-1 text-xs text-bad">{act.error}</p>}
      </Alert>
    </div>
  );
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const [run, setRun] = useState<Run | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<RoleKey | "">("");
  const [nonce, setNonce] = useState(0);
  const last = useRef(0);
  const act = useAction();

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api.get<Run>(`/api/agent/runs/${id}?after=${last.current}`);
        if (!alive) return;
        if (r.steps?.length) {
          last.current = r.steps[r.steps.length - 1].seq;
          setSteps((prev) => [...prev, ...r.steps!]);
        }
        setRun(r);
        setError(null);
        timer = setTimeout(poll, ACTIVE.includes(r.status) ? 1200 : 5000);
      } catch (e) {
        if (alive) setError(errorMessage(e));
        timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, nonce]);

  const counts = useMemo(() => {
    const c: Partial<Record<RoleKey, number>> = {};
    for (const s of steps) if (s.phase === "tool") c[s.role] = (c[s.role] || 0) + 1;
    return c;
  }, [steps]);
  const activeRole = [...steps].reverse().find((s) => s.phase === "tool" || s.phase === "delegate")?.role;

  if (error && !run) return <Alert tone="bad">{error}</Alert>;
  if (!run) return <Loading />;
  const out = run.outputs as Record<string, unknown>;
  const budget = run.cost_budget_usd + (run.approved_extra_usd || 0);
  const costPct = budget ? Math.min(100, (run.cost_usd / budget) * 100) : 0;
  const stepPct = Math.min(100, (run.step_count / run.max_steps) * 100);
  const mockSteps = steps.filter((s) => s.is_mock).length;
  const shown = roleFilter ? steps.filter((s) => s.role === roleFilter && s.phase !== "delegate") : steps;
  const assetIds = (Array.isArray(out.asset_ids) ? out.asset_ids : []) as number[];
  const refresh = () => { last.current = 0; setSteps([]); setNonce((n) => n + 1); };
  const post = async (path: string) => { if (await act.run(() => api.post(path))) refresh(); };

  return (
    <div>
      <PageHeader
        title="Agent run"
        subtitle={<span className="text-ink">“{run.goal}”</span>}
        actions={
          <>
            {ACTIVE.includes(run.status) && can.edit && <Button busy={act.busy} onClick={() => post(`/api/agent/runs/${id}/pause`)}>Pause</Button>}
            {run.status === "paused" && can.edit && <Button variant="primary" busy={act.busy} onClick={() => post(`/api/agent/runs/${id}/unpause`)}>Resume</Button>}
            {["blocked", "failed"].includes(run.status) && can.edit && <Button variant="primary" busy={act.busy} onClick={() => post(`/api/agent/runs/${id}/retry`)}>Retry from where it stopped</Button>}
            {[...ACTIVE, "paused", "awaiting_approval"].includes(run.status) && can.edit && <Button variant="danger" busy={act.busy} onClick={() => { if (confirm("Cancel this run? Completed work is kept.")) void post(`/api/agent/runs/${id}/cancel`); }}>Cancel</Button>}
            {run.status === "awaiting_approval" && <LinkButton href="/approvals" variant="primary">Open Approval Inbox</LinkButton>}
            {run.status === "awaiting_approval" && can.own && !out.awaiting_budget_request && <Button busy={act.busy} onClick={() => post(`/api/agent/runs/${id}/resume`)}>Resume with what&apos;s approved</Button>}
          </>
        }
      />
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      {typeof out.awaiting_budget_request === "number" && <BudgetRequest id={out.awaiting_budget_request} onDone={refresh} />}

      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <Card><div className="text-xs font-semibold uppercase text-muted">Status</div><div className="mt-1 flex items-center gap-2"><RunStatusBadge status={run.status} />{ACTIVE.includes(run.status) && <CircleDot className="h-4 w-4 animate-pulse text-info" />}</div>
          {run.completion_reason && <div className="mt-1 text-xs text-muted">{run.completion_reason.replace(/_/g, " ")}</div>}
          {run.recoveries > 0 && <div className="mt-1"><Badge tone="info">recovered {run.recoveries}×</Badge></div>}</Card>
        <Card><div className="text-xs font-semibold uppercase text-muted">Tool steps</div><div className="mt-1 text-lg font-bold">{run.step_count} / {run.max_steps}</div>
          <div className="mt-1 h-1.5 rounded bg-panel-2"><div className="h-1.5 rounded bg-accent transition-all" style={{ width: `${stepPct}%` }} /></div></Card>
        <Card><div className="text-xs font-semibold uppercase text-muted">Provider cost (est.)</div><div className="mt-1 text-lg font-bold"><Money usd={run.cost_usd} /></div>
          <div className="mt-1 h-1.5 rounded bg-panel-2"><div className={cx("h-1.5 rounded transition-all", costPct > 85 ? "bg-bad" : "bg-warm")} style={{ width: `${costPct}%` }} /></div>
          <div className="mt-1 text-xs text-muted">of ${budget.toFixed(2)} run budget{run.planner === "demo-planner" && " · demo makes no paid calls"}</div></Card>
        <Card><div className="text-xs font-semibold uppercase text-muted">Planner</div><div className="mt-1 text-sm font-semibold">{run.planner}</div>
          <div className="text-xs text-muted">{fmtNum(run.tokens_used)} tokens · started {fmtDate(run.started_at, can.tz)}</div>
          {mockSteps > 0 && <div className="mt-1"><Badge tone="demo">{mockSteps} step(s) used fixtures or simulations</Badge></div>}</Card>
      </div>

      <Card className="mb-4" title="Agent team" subtitle="The orchestrator delegates each phase to a specialist. Click one to filter the timeline.">
        <div className="flex flex-wrap gap-2">
          {ROLE_ORDER.map((r) => (
            <button key={r} onClick={() => setRoleFilter(roleFilter === r ? "" : r)}
              className={cx("flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition", roleFilter === r ? "border-accent bg-accent-soft" : "border-line hover:bg-panel-2")}>
              <span className={cx("h-2.5 w-2.5 rounded-full", ROLES[r].dot, ACTIVE.includes(run.status) && activeRole === r && "animate-ping")} />
              <span><span className="block font-semibold text-ink">{ROLES[r].short}</span><span className="text-muted">{counts[r] || 0} action(s)</span></span>
            </button>
          ))}
          {roleFilter && <Button size="sm" variant="ghost" onClick={() => setRoleFilter("")}>Show all</Button>}
        </div>
      </Card>

      {run.outcome_summary && <div className="mb-4"><Alert tone={run.status === "completed" ? "ok" : run.status === "awaiting_approval" ? "warn" : "info"} title="Outcome">{run.outcome_summary}</Alert></div>}
      {run.error && <div className="mb-4"><Alert tone="bad">{run.error}</Alert></div>}
      {run.blockers?.length > 0 && (
        <div className="mb-4"><Alert tone="warn" title="Blocked items (the agent continued without them where it could)">{run.blockers.map((b) => b.replace(/_/g, " ")).join(" · ")}</Alert></div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="Live activity" subtitle="Each step is persisted by the backend as it happens. Decisions and re-plans are highlighted; open Details for the tool, inputs, result, evidence and cost.">
          <ol className="relative space-y-3 border-l border-line pl-0 [&>li]:ml-[-12px]">
            {shown.map((s) => <StepRow key={s.seq} s={s} runId={run.id} />)}
          </ol>
          {ACTIVE.includes(run.status) && <div className="mt-4 flex items-center gap-2 text-sm text-muted"><CircleDot className="h-4 w-4 animate-pulse text-info" /> Working…</div>}
        </Card>
        <div className="space-y-5">
          <Card title="Plan">
            <ol className="space-y-1.5 text-sm">
              {run.plan.map((p) => (
                <li key={p.id} className="flex gap-2">
                  <span className={cx("mt-0.5 w-4 shrink-0 text-center text-xs font-bold", p.status === "done" ? "text-ok" : p.status === "blocked" || p.status === "failed" ? "text-bad" : p.status === "skipped" ? "text-muted" : "text-info")}>
                    {p.status === "done" ? "✓" : p.status === "blocked" ? "!" : p.status === "failed" ? "✕" : p.status === "skipped" ? "–" : "○"}
                  </span>
                  <span className={cx("min-w-0", p.status === "skipped" && "text-muted line-through")}>
                    <span className="flex flex-wrap items-center gap-1"><code className="text-xs">{p.tool}</code>{p.role && <RoleBadge role={p.role} />}{p.inserted && <Badge tone="warm">added</Badge>}{p.after_approval && <Badge tone="warn">after approval</Badge>}</span>
                    <span className="block text-xs text-muted">{p.purpose}{p.note ? ` (${p.note})` : ""}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Card>
          <Card title="Outputs">
            <ul className="space-y-1.5 text-sm">
              {typeof out.campaign_id === "number" && <li><Link className="text-accent hover:underline" href={`/campaigns/${out.campaign_id}`}>Campaign #{out.campaign_id} gallery →</Link></li>}
              {Array.isArray(out.content_ids) && <li>{out.content_ids.length} main post(s){Array.isArray(out.variant_ids) && ` + ${out.variant_ids.length} platform variant(s)`}</li>}
              {Array.isArray(out.awaiting_ids) && out.awaiting_ids.length > 0 && <li><Link className="text-accent hover:underline" href="/approvals">{out.awaiting_ids.length} item(s) for approval →</Link></li>}
              {Array.isArray(out.scheduled_ids) && <li><Link className="text-accent hover:underline" href="/calendar">{out.scheduled_ids.length} scheduled →</Link></li>}
              {Array.isArray(out.finding_ids) && <li><Link className="text-accent hover:underline" href={`/research?run_id=${run.id}`}>{out.finding_ids.length} research finding(s) →</Link></li>}
              {Array.isArray(out.hypothesis_ids) && <li>{out.hypothesis_ids.length} hypotheses ranked</li>}
              {typeof out.report_id === "number" && <li><Link className="text-accent hover:underline" href={`/reports/${out.report_id}`}>Report #{out.report_id} →</Link></li>}
              {typeof out.next_experiment_id === "number" && <li><Link className="text-accent hover:underline" href="/experiments">Next experiment planned →</Link></li>}
              {Boolean(out.brand_snapshot) && <li className="text-xs text-muted">Brand snapshot {(out.brand_snapshot as { hash: string }).hash} used by every role</li>}
              {Object.keys(out).length === 0 && <li className="text-muted">Nothing yet.</li>}
            </ul>
            {assetIds.length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-xs font-semibold uppercase text-muted">Rendered images ({assetIds.length})</div>
                <div className="grid grid-cols-4 gap-1.5">
                  {assetIds.slice(-12).map((a) => (
                    <Link key={a} href={`/assets?focus=${a}`} className="overflow-hidden rounded border border-line">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={`/api/assets/${a}/file`} alt={`Rendered image ${a}`} className="aspect-[4/5] w-full bg-panel-2 object-cover" loading="lazy" />
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
