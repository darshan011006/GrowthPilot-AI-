"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth, useCan } from "@/components/auth";
import { Money, RunStatusBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Field, Input, Loading, PageHeader, Stat, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { cx, fmtNum, fmtRelative } from "@/lib/format";
import type { UsageSummary } from "@/lib/types";

interface Budgets { run_budget_usd: number; monthly_budget_usd: number; approval_threshold_usd: number; search_requests_per_run: number; search_requests_per_day: number }
interface SettingsData { workspace: Budgets & { name: string; timezone: string; agent_max_steps: number; agent_token_budget: number; agent_timeout_minutes: number } }

export default function UsagePage() {
  const can = useCan();
  const { state } = useAuth();
  const { data, loading, error, reload } = useApi<UsageSummary>("/api/usage");
  const settings = useApi<SettingsData>("/api/settings");
  const [edit, setEdit] = useState<Budgets | null>(null);
  const act = useAction();
  const [ok, setOk] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  const ws = settings.data?.workspace;
  const b = edit ?? (ws ? { run_budget_usd: ws.run_budget_usd, monthly_budget_usd: ws.monthly_budget_usd, approval_threshold_usd: ws.approval_threshold_usd, search_requests_per_run: ws.search_requests_per_run, search_requests_per_day: ws.search_requests_per_day } : null);
  const pct = data.monthly_budget_usd ? Math.min(100, (data.month_cost_usd / data.monthly_budget_usd) * 100) : 0;
  const save = async () => {
    if (!ws || !b) return;
    const { name, timezone, agent_max_steps, agent_token_budget, agent_timeout_minutes } = ws;
    if (await act.run(() => api.put("/api/settings", { name, timezone, agent_max_steps, agent_token_budget, agent_timeout_minutes, ...b }))) {
      setOk(true); setEdit(null); settings.reload(); reload();
    }
  };
  return (
    <div>
      <PageHeader title="Usage & Budgets" subtitle="Every paid provider call is estimated before it runs and recorded after. Paid steps that would cross a budget pause the agent and ask an owner first." />
      {state?.mode === "demo" && <div className="mb-4"><Alert tone="demo">Demo mode makes no paid calls, so costs stay at $0. Budgets apply as soon as live mode uses Gemini, Claude, Brave or an image model.</Alert></div>}
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="This month (est.)" value={<Money usd={data.month_cost_usd} />} hint={`since ${data.month_start}`} />
        <Stat label="Monthly budget" value={data.monthly_budget_usd != null ? `$${data.monthly_budget_usd.toFixed(2)}` : "—"} hint={<span className="block h-1.5 rounded bg-panel-2"><span className={cx("block h-1.5 rounded", pct > 85 ? "bg-bad" : "bg-accent")} style={{ width: `${pct}%` }} /></span>} />
        <Stat label="Per-run budget" value={data.run_budget_usd != null ? `$${data.run_budget_usd.toFixed(2)}` : "—"} hint={`single step over $${data.approval_threshold_usd?.toFixed(2)} needs approval`} />
        <Stat label="Web search caps" value={`${data.search_requests_per_run}/run`} hint={`${data.search_requests_per_day} per day · cached 24 h`} />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <Card title="By provider this month">
            {data.by_provider.length === 0 ? <p className="text-sm text-muted">No provider calls yet.</p> : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">Provider</th><th className="pr-3">Operation</th><th className="pr-3">Calls</th><th className="pr-3">Tokens in/out</th><th className="pr-3">Cached</th><th>Cost</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {data.by_provider.map((r) => (
                    <tr key={`${r.provider}-${r.operation}`}><td className="py-1.5 pr-3 font-medium">{r.provider}</td><td className="pr-3">{r.operation}</td><td className="pr-3">{r.calls}</td>
                      <td className="pr-3">{fmtNum(r.input_tokens)} / {fmtNum(r.output_tokens)}</td><td className="pr-3">{r.cached}</td><td><Money usd={r.cost_usd} /></td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Recent agent runs">
            <ul className="divide-y divide-line text-sm">
              {data.runs.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <Link href={`/agent/${r.id}`} className="min-w-0 flex-1 truncate hover:underline">{r.goal}</Link>
                  <span className="flex items-center gap-2 text-xs text-muted"><RunStatusBadge status={r.status} /><Money usd={r.cost_usd} /> of ${r.budget_usd.toFixed(2)} · {fmtNum(r.tokens)} tok · {fmtRelative(r.created_at)}</span>
                </li>
              ))}
              {data.runs.length === 0 && <li className="py-2 text-muted">No runs yet.</li>}
            </ul>
          </Card>
          <Card title="Recent provider calls">
            {data.recent.length === 0 ? <p className="text-sm text-muted">None yet.</p> : (
              <ul className="space-y-1 text-xs">{data.recent.map((u, i) => <li key={i} className="flex flex-wrap gap-2"><Badge>{u.provider}</Badge>{u.operation} {u.model && <span className="text-muted">{u.model}</span>}{u.cached && <Badge tone="ok">cache</Badge>}<span className="ml-auto"><Money usd={u.cost_usd} /> · {fmtRelative(u.created_at)}</span></li>)}</ul>
            )}
          </Card>
        </div>
        <div className="space-y-5">
          <Card title="Budgets & caps" subtitle="Owner only. The agent asks for approval before crossing any of these.">
            {!b ? <Loading /> : (
              <fieldset disabled={!can.own}>
                <Field label="Per-run budget (USD)">{(id) => <Input id={id} type="number" min={0} step="0.1" value={b.run_budget_usd} onChange={(e) => setEdit({ ...b, run_budget_usd: Number(e.target.value) })} />}</Field>
                <Field label="Monthly budget (USD)">{(id) => <Input id={id} type="number" min={0} step="1" value={b.monthly_budget_usd} onChange={(e) => setEdit({ ...b, monthly_budget_usd: Number(e.target.value) })} />}</Field>
                <Field label="Approval threshold for one step (USD)">{(id) => <Input id={id} type="number" min={0} step="0.05" value={b.approval_threshold_usd} onChange={(e) => setEdit({ ...b, approval_threshold_usd: Number(e.target.value) })} />}</Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Searches per run">{(id) => <Input id={id} type="number" min={0} value={b.search_requests_per_run} onChange={(e) => setEdit({ ...b, search_requests_per_run: Number(e.target.value) })} />}</Field>
                  <Field label="Searches per day">{(id) => <Input id={id} type="number" min={0} value={b.search_requests_per_day} onChange={(e) => setEdit({ ...b, search_requests_per_day: Number(e.target.value) })} />}</Field>
                </div>
                {act.error && <Alert tone="bad">{act.error}</Alert>}
                {ok && <Alert tone="ok">Saved.</Alert>}
                {can.own && <Button variant="primary" busy={act.busy} onClick={save}>Save budgets</Button>}
              </fieldset>
            )}
          </Card>
          <Card title="Price list used for estimates" subtitle={`Checked ${data.prices.checked}. Free tiers and credits aren't deducted; your provider's bill is authoritative.`}>
            <ul className="space-y-1 text-xs">
              {Object.entries(data.prices.token_prices_per_million).map(([m, [i, o]]) => <li key={m} className="flex justify-between gap-2"><code>{m}</code><span>${i} / ${o} per 1M tokens</span></li>)}
              {Object.entries(data.prices.unit_prices).map(([m, u]) => <li key={m} className="flex justify-between gap-2"><code>{m}</code><span>${u} each</span></li>)}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
