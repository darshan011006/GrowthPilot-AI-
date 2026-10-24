"use client";

import Link from "next/link";
import { useCan } from "@/components/auth";
import { PlatformChip, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Loading, PageHeader, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtPct } from "@/lib/format";
import type { Experiment, Recommendation } from "@/lib/types";

const CONCLUSION: Record<string, ["ok" | "bad" | "warn" | "neutral", string]> = {
  supported: ["ok", "Supported (association)"],
  not_supported: ["bad", "Not supported"],
  inconclusive: ["warn", "Inconclusive"],
  "": ["neutral", "Not evaluated"],
};

export default function ExperimentsPage() {
  const can = useCan();
  const { data, loading, error, reload } = useApi<Experiment[]>("/api/experiments");
  const recs = useApi<Recommendation[]>("/api/recommendations");
  const act = useAction();

  return (
    <div>
      <PageHeader title="Experiments & adaptive loop" subtitle="Observe → hypothesise → test → evaluate → learn → next experiment. Conclusions describe associations in small samples, never proven causes."
        actions={<Link href="/agent" className="rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-accent-ink">Run an evaluation</Link>} />
      {act.error && <div className="mb-3"><Alert tone="bad">{act.error}</Alert></div>}
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? <Empty title="No experiments yet">Campaign runs create an A/B experiment for the selected hypothesis.</Empty> : (
        <div className="space-y-4">
          {data.map((e) => {
            const [tone, label] = CONCLUSION[e.conclusion] ?? CONCLUSION[""];
            const per = e.result?.per_variant || {};
            return (
              <Card key={e.id} title={<span className="flex flex-wrap items-center gap-2">{e.name}<Badge tone={tone}>{label}</Badge><Badge>{e.status}</Badge><SyntheticBadge show={e.is_synthetic || e.data_source === "synthetic"} /></span>}
                subtitle={e.hypothesis?.statement || (e.learnings.startsWith("Proposed") ? e.learnings : undefined)}
                actions={can.edit && e.status !== "planned" && <Button size="sm" busy={act.busy} onClick={async () => { await act.run(() => api.post(`/api/experiments/${e.id}/evaluate`)); reload(); }}>Re-evaluate</Button>}>
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="text-sm">
                    <div className="mb-1 text-xs font-semibold uppercase text-muted">Variants</div>
                    {e.variants.map((v) => (
                      <div key={v.label} className="mb-1"><strong>{v.label}</strong>: {v.description}
                        <div className="text-xs text-muted">{per[v.label] ? `n=${per[v.label].n} · mean ${e.primary_metric.replace(/_/g, " ")} ${fmtPct(per[v.label].mean ?? per[v.label].mean_engagement_rate, 2)}` : `${e.variant_posts?.[v.label] ?? 0} published post(s)`}</div></div>
                    ))}
                  </div>
                  <div className="text-sm">
                    <div className="mb-1 text-xs font-semibold uppercase text-muted">Success criterion</div>
                    {e.success_criteria.map((c, i) => <div key={i}>{c.metric.replace(/_/g, " ")}: {c.variant || "B"} vs {c.baseline || "A"} lift ≥ {fmtPct(c.target, 0)}</div>)}
                    <div className="text-xs text-muted">Minimum {e.min_sample_per_variant} posts per variant</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">Primary metric: <Badge>{e.primary_metric.replace(/_/g, " ")}</Badge>{e.result?.platform && <>on <PlatformChip platform={e.result.platform} withLabel /></>}</div>
                    {e.baseline?.note && <div className="mt-1 text-xs text-muted">Baseline: {e.baseline.value != null ? fmtPct(e.baseline.value, 2) : "—"} — {e.baseline.note}</div>}
                    {e.result?.lift !== undefined && <div className="mt-2">Observed lift <strong>{fmtPct(e.result.lift)}</strong>, p≈{e.result.p_value?.toFixed(3)} {e.confidence && <Badge tone={e.confidence === "high" ? "ok" : e.confidence === "medium" ? "info" : "warn"}>confidence {e.confidence}</Badge>}</div>}
                    {e.result?.vs_historical_baseline && <div className="mt-1 text-xs">vs earlier posts: <strong>{fmtPct(e.result.vs_historical_baseline.lift)}</strong> (n={e.result.vs_historical_baseline.baseline_n})</div>}
                    {(e.comparison_method || e.result?.method) && <div className="mt-1 text-xs text-muted">{e.comparison_method || e.result?.method}</div>}
                    <div className="mt-1 text-xs text-muted">Evaluation window: {e.evaluation_window_days} days</div>
                  </div>
                  <div className="text-sm">
                    <div className="mb-1 text-xs font-semibold uppercase text-muted">What we learned</div>
                    <p>{e.learnings || "—"}</p>
                    {e.next_recommendation && <p className="mt-2"><span className="text-muted">Next:</span> {e.next_recommendation}</p>}
                    {e.evaluated_at && <p className="mt-1 text-xs text-muted">Evaluated {fmtDate(e.evaluated_at, can.tz)}</p>}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
      <Card className="mt-6" title="Recommendations">
        {!recs.data?.length ? <p className="text-sm text-muted">None yet.</p> : (
          <ul className="divide-y divide-line">
            {recs.data.map((r) => (
              <li key={r.id} className="py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2"><strong>{r.title}</strong><Badge tone={r.priority === "high" ? "warm" : "neutral"}>{r.priority}</Badge><Badge>{r.status}</Badge><SyntheticBadge show={r.is_synthetic} /></div>
                <p className="mt-1">{r.detail}</p>
                {r.rationale && <p className="mt-1 text-muted">Why: {r.rationale}</p>}
                {r.uncertainty && <p className="mt-1 text-xs text-muted">Uncertainty: {r.uncertainty}</p>}
                {r.evidence.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{r.evidence.map((e, i) => <Badge key={i}>{e.type}: {e.summary}</Badge>)}</div>}
                {r.proposed_change?.type && (
                  <div className="mt-2 rounded-lg border border-line bg-panel-2 p-2 text-xs"><strong>Proposed change:</strong> {r.proposed_change.detail}
                    {r.status === "applied" && <Badge tone="ok" className="ml-1">applied {fmtDate(r.decided_at, can.tz)}</Badge>}</div>
                )}
                {can.edit && r.status === "open" && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {r.proposed_change?.type && can.own && <Button size="sm" variant="primary" onClick={async () => { if (confirm(`Apply this change to the brand profile?\n\n${r.proposed_change.detail}`)) { await act.run(() => api.post(`/api/recommendations/${r.id}/apply`)); recs.reload(); } }}>Approve & apply change</Button>}
                    <Button size="sm" onClick={async () => { await act.run(() => api.post(`/api/recommendations/${r.id}/status`, { status: "accepted" })); recs.reload(); }}>Accept (no automatic change)</Button>
                    <Button size="sm" variant="ghost" onClick={async () => { await act.run(() => api.post(`/api/recommendations/${r.id}/status`, { status: "dismissed" })); recs.reload(); }}>Dismiss</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
