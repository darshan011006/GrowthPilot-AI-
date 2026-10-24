"use client";

import { AlertTriangle, Brain, CheckCircle2, CircleDot, Eye, Flag, GitBranch, Hand, ListChecks, Wrench } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useCan } from "@/components/auth";
import { MockBadge, RunStatusBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, LinkButton, Loading, PageHeader, useAction } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { cx, fmtDate, fmtNum } from "@/lib/format";
import type { Run, Step } from "@/lib/types";

const PHASE: Record<Step["phase"], { icon: typeof Eye; label: string; cls: string }> = {
  observe: { icon: Eye, label: "Observe", cls: "text-info" },
  plan: { icon: ListChecks, label: "Plan", cls: "text-accent" },
  tool: { icon: Wrench, label: "Tool", cls: "text-ink" },
  evaluate: { icon: CheckCircle2, label: "Evaluate", cls: "text-ok" },
  replan: { icon: GitBranch, label: "Re-plan", cls: "text-warm" },
  decision: { icon: Brain, label: "Decision", cls: "text-accent" },
  approval: { icon: Hand, label: "Approval", cls: "text-warn" },
  finish: { icon: Flag, label: "Finish", cls: "text-ok" },
  error: { icon: AlertTriangle, label: "Error", cls: "text-bad" },
};

const ACTIVE = ["queued", "running"];

function StepRow({ s }: { s: Step }) {
  const [open, setOpen] = useState(false);
  const meta = PHASE[s.phase] ?? PHASE.tool;
  const Icon = meta.icon;
  const tone = s.status === "error" ? "bad" : s.status === "blocked" ? "warn" : undefined;
  return (
    <li className="relative pl-8">
      <span className={cx("absolute left-0 top-0.5 grid h-6 w-6 place-items-center rounded-full border border-line bg-panel", meta.cls)}><Icon className="h-3.5 w-3.5" aria-hidden /></span>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="font-semibold text-muted">#{s.seq} {meta.label}</span>
        {s.tool && <code className="rounded bg-panel-2 px-1.5 py-0.5 text-[11px] font-semibold">{s.tool}</code>}
        {tone && <Badge tone={tone}>{s.status}</Badge>}
        {s.attempt > 1 && <Badge tone="info">attempt {s.attempt}</Badge>}
        <MockBadge show={s.is_mock} />
        {s.duration_ms > 0 && <span className="text-muted">{s.duration_ms} ms</span>}
        {s.tokens > 0 && <span className="text-muted">{fmtNum(s.tokens)} tokens</span>}
      </div>
      <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink">{s.message}</p>
      {(s.input || s.output) && (
        <button onClick={() => setOpen(!open)} className="mt-1 text-xs font-semibold text-info hover:underline" aria-expanded={open}>
          {open ? "Hide" : "Show"} tool input/output
        </button>
      )}
      {open && (
        <div className="mt-1 grid gap-2 md:grid-cols-2">
          {s.input && <pre className="max-h-72 overflow-auto rounded-lg bg-panel-2 p-2 text-[11px]">{JSON.stringify(s.input, null, 2)}</pre>}
          {s.output && <pre className="max-h-72 overflow-auto rounded-lg bg-panel-2 p-2 text-[11px]">{JSON.stringify(s.output, null, 2)}</pre>}
        </div>
      )}
    </li>
  );
}

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const [run, setRun] = useState<Run | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [error, setError] = useState<string | null>(null);
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
  }, [id]);

  if (error && !run) return <Alert tone="bad">{error}</Alert>;
  if (!run) return <Loading />;
  const out = run.outputs as Record<string, unknown>;
  const tokenPct = run.token_budget ? Math.min(100, (run.tokens_used / run.token_budget) * 100) : 0;
  const stepPct = Math.min(100, (run.step_count / run.max_steps) * 100);
  const mockSteps = steps.filter((s) => s.is_mock).length;

  return (
    <div>
      <PageHeader
        title="Agent run"
        subtitle={<span className="text-ink">“{run.goal}”</span>}
        actions={
          <>
            {ACTIVE.includes(run.status) && can.edit && <Button variant="danger" busy={act.busy} onClick={() => act.run(() => api.post(`/api/agent/runs/${id}/cancel`))}>Cancel run</Button>}
            {run.status === "awaiting_approval" && <LinkButton href="/approvals" variant="primary">Open Approval Inbox</LinkButton>}
            {run.status === "awaiting_approval" && can.own && <Button busy={act.busy} onClick={() => act.run(() => api.post(`/api/agent/runs/${id}/resume`))}>Resume with what&apos;s approved</Button>}
          </>
        }
      />
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Card><div className="text-xs font-semibold uppercase text-muted">Status</div><div className="mt-1 flex items-center gap-2"><RunStatusBadge status={run.status} />{ACTIVE.includes(run.status) && <CircleDot className="h-4 w-4 animate-pulse text-info" />}</div>
          {run.completion_reason && <div className="mt-1 text-xs text-muted">{run.completion_reason}</div>}</Card>
        <Card><div className="text-xs font-semibold uppercase text-muted">Tool steps</div><div className="mt-1 text-lg font-bold">{run.step_count} / {run.max_steps}</div>
          <div className="mt-1 h-1.5 rounded bg-panel-2"><div className="h-1.5 rounded bg-accent" style={{ width: `${stepPct}%` }} /></div></Card>
        <Card><div className="text-xs font-semibold uppercase text-muted">Token budget</div><div className="mt-1 text-lg font-bold">{fmtNum(run.tokens_used)}</div>
          <div className="mt-1 h-1.5 rounded bg-panel-2"><div className="h-1.5 rounded bg-warm" style={{ width: `${tokenPct}%` }} /></div>
          <div className="mt-1 text-xs text-muted">of {fmtNum(run.token_budget)}{run.planner === "demo-planner" && " · demo planner uses no LLM tokens"}</div></Card>
        <Card><div className="text-xs font-semibold uppercase text-muted">Planner</div><div className="mt-1 text-sm font-semibold">{run.planner}</div>
          <div className="text-xs text-muted">Started {fmtDate(run.started_at, can.tz)}</div>{mockSteps > 0 && <div className="mt-1"><Badge tone="demo">{mockSteps} step(s) used mocks/fixtures</Badge></div>}</Card>
      </div>

      {run.outcome_summary && <div className="mb-4"><Alert tone={run.status === "completed" ? "ok" : run.status === "awaiting_approval" ? "warn" : "info"} title="Outcome">{run.outcome_summary}</Alert></div>}
      {run.error && <div className="mb-4"><Alert tone="bad">{run.error}</Alert></div>}
      {run.blockers?.length > 0 && (
        <div className="mb-4"><Alert tone="warn" title="Blocked items (the agent continued without them)">{run.blockers.map((b) => b.replace(/_/g, " ")).join(" · ")}</Alert></div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="Execution trace" subtitle="Every step is persisted by the backend as it happens.">
          <ol className="relative space-y-4 border-l border-line pl-0 [&>li]:ml-[-12px]">
            {steps.map((s) => <StepRow key={s.seq} s={s} />)}
          </ol>
          {ACTIVE.includes(run.status) && <div className="mt-4 text-sm text-muted">Working…</div>}
        </Card>
        <div className="space-y-5">
          <Card title="Plan">
            <ol className="space-y-1.5 text-sm">
              {run.plan.map((p) => (
                <li key={p.id} className="flex gap-2">
                  <span className={cx("mt-0.5 w-4 shrink-0 text-center text-xs font-bold", p.status === "done" ? "text-ok" : p.status === "blocked" || p.status === "failed" ? "text-bad" : p.status === "skipped" ? "text-muted" : "text-info")}>
                    {p.status === "done" ? "✓" : p.status === "blocked" ? "!" : p.status === "failed" ? "✕" : p.status === "skipped" ? "–" : "○"}
                  </span>
                  <span className={cx(p.status === "skipped" && "text-muted line-through")}>
                    <code className="text-xs">{p.tool}</code>{p.inserted && <Badge tone="warm" className="ml-1">added</Badge>}
                    <span className="block text-xs text-muted">{p.purpose}{p.note ? ` (${p.note})` : ""}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Card>
          <Card title="Outputs">
            <ul className="space-y-1.5 text-sm">
              {typeof out.campaign_id === "number" && <li><Link className="text-accent hover:underline" href={`/campaigns/${out.campaign_id}`}>Campaign #{out.campaign_id} →</Link></li>}
              {Array.isArray(out.awaiting_ids) && out.awaiting_ids.length > 0 && <li><Link className="text-accent hover:underline" href="/approvals">{out.awaiting_ids.length} post(s) for approval →</Link></li>}
              {Array.isArray(out.finding_ids) && <li><Link className="text-accent hover:underline" href={`/research?run_id=${run.id}`}>{out.finding_ids.length} research finding(s) →</Link></li>}
              {Array.isArray(out.hypothesis_ids) && <li>{out.hypothesis_ids.length} hypotheses ranked</li>}
              {typeof out.report_id === "number" && <li><Link className="text-accent hover:underline" href={`/reports/${out.report_id}`}>Report #{out.report_id} →</Link></li>}
              {typeof out.next_experiment_id === "number" && <li><Link className="text-accent hover:underline" href="/experiments">Next experiment planned →</Link></li>}
              {Object.keys(out).length === 0 && <li className="text-muted">Nothing yet.</li>}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
