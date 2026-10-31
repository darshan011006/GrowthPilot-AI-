"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
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
      <PageHeader
        title="Agent Command Centre"
        subtitle="Give GrowthPilot one marketing goal. An orchestrator delegates to six specialists (research, strategy, creative, verification, distribution, analyst), re-plans from real tool results, stays within budget, and stops for your approval before anything is scheduled on any platform."
      />
      <Card className="mb-6">
        <form onSubmit={submit}>
          <label htmlFor="goal" className="mb-1 block text-sm font-semibold">Goal</label>
          <Textarea id="goal" rows={3} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. Create a seven-day Deepavali campaign across Instagram, Facebook, Pinterest and Threads" />
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
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button variant="primary" type="submit" busy={start.busy} disabled={!can.edit || goal.trim().length < 5}>Start run</Button>
            <span className="text-xs text-muted">
              Planner: {state?.mode === "demo" ? "deterministic demo orchestrator (no LLM, no paid calls, labelled fixtures)" : "the configured LLM (Gemini or Claude), choosing from 26 typed, role-tagged tools"}.
            </span>
          </div>
        </form>
      </Card>

      <Card title="Runs">
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
