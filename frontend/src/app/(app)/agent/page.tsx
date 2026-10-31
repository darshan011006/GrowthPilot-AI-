"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { useAuth, useCan } from "@/components/auth";
import { RunStatusBadge } from "@/components/domain";
import { Alert, Button, Card, Empty, Loading, PageHeader, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { Run } from "@/lib/types";

export default function AgentPage() {
  const router = useRouter();
  const { state } = useAuth();
  const can = useCan();
  const runs = useApi<Run[]>("/api/agent/runs");
  const examples = useApi<string[]>("/api/agent/examples");
  const [goal, setGoal] = useState("");
  const start = useAction();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = await start.run(() => api.post<Run>("/api/agent/runs", { goal }));
    if (r) router.push(`/agent/${r.id}`);
  };

  return (
    <div>
      <PageHeader title="AI Content Engine" subtitle="Your autonomous social media growth workspace." />
      <Card className="mb-6 rounded-[28px] p-6 md:p-8">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-3"><span className="grid h-12 w-12 place-items-center rounded-full border border-accent/30 bg-accent-soft text-accent"><Sparkles className="h-5 w-5" /></span><div><h2 className="font-semibold">GrowthPilot orchestrator</h2><p className="text-xs text-muted">{state?.mode === "demo" ? "Demo workflow · no external AI calls" : "Ready to plan with your configured AI provider"}</p></div></div><span className="rounded-full border border-ok/30 bg-ok-soft px-3 py-1.5 text-xs font-semibold text-ok">Ready</span></div>
        <div className="mb-5 rounded-2xl border border-line bg-[#0b120e] px-4 py-8 text-center"><div className="mx-auto mb-3 flex h-12 items-center justify-center gap-1.5" aria-hidden>{[14, 26, 38, 22, 32, 16, 30, 20, 38, 24, 15, 28, 18, 34, 22].map((height, i) => <span key={i} className="w-1.5 rounded-full bg-accent/30" style={{ height }} />)}</div><p className="text-sm text-muted">Describe a goal below. Your workflow will research, plan, create and pause for your approval.</p></div>
        <form onSubmit={submit}>
          <label htmlFor="goal" className="sr-only">Goal</label>
          <div className="flex flex-col gap-3 md:flex-row md:items-stretch"><Textarea id="goal" rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Tell your AI team what to create… e.g. Plan a week of Instagram content for our furniture brand" className="min-h-14 flex-1 rounded-2xl" /><Button variant="primary" className="min-h-14 rounded-2xl px-6" type="submit" busy={start.busy} disabled={!can.edit || goal.trim().length < 5}>Start run</Button></div>
          {examples.data && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {examples.data.map((ex) => (
                <button type="button" key={ex} onClick={() => setGoal(ex)} className="rounded-full border border-line bg-panel-2 px-2.5 py-1 text-left text-xs text-ink hover:border-accent">
                  {ex}
                </button>
              ))}
            </div>
          )}
          {start.error && <div className="mt-3"><Alert tone="bad">{start.error}</Alert></div>}
          <div className="mt-4 flex flex-wrap items-center gap-3"><span className="text-xs text-muted">{state?.mode === "demo" ? "Deterministic demo orchestrator · no LLM or paid calls · fixtures are labelled" : "Uses the configured AI provider and typed, role-tagged tools"}</span></div>
        </form>
      </Card>

      <Card title="Recent workflows" subtitle="Progress, outputs and approval checkpoints" className="rounded-3xl">
        {runs.loading && !runs.data ? <Loading /> : runs.error ? <Alert tone="bad">{runs.error}</Alert> : !runs.data?.length ? (
          <Empty title="No runs yet">Pick an example above to see the full workflow.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted">
                <tr><th className="py-2 pr-3">Goal</th><th className="pr-3">Status</th><th className="pr-3">Steps</th><th className="pr-3">Cost (est.)</th><th className="pr-3">Planner</th><th>Started</th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2 pr-3"><Link href={`/agent/${r.id}`} className="font-medium hover:underline">{r.goal}</Link></td>
                    <td className="pr-3"><RunStatusBadge status={r.status} /></td>
                    <td className="pr-3 text-muted">{r.step_count}/{r.max_steps}</td>
                    <td className="pr-3 text-muted">${(r.cost_usd ?? 0).toFixed(4)}</td>
                    <td className="pr-3 text-muted">{r.planner}</td>
                    <td className="text-muted">{fmtRelative(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
