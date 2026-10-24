"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCan } from "@/components/auth";
import { ContentStatusBadge, EvidenceBadge, SourceLink, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, KeyValue, Loading, PageHeader, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtPct, titleCase } from "@/lib/format";
import type { Campaign, ContentItem, Experiment, Finding, Hypothesis, Recommendation, ReportSummary } from "@/lib/types";

interface Detail {
  campaign: Campaign;
  items: ContentItem[];
  hypotheses: Hypothesis[];
  evidence: Finding[];
  experiments: Experiment[];
  recommendations: Recommendation[];
  reports: ReportSummary[];
}

const CRITERIA = ["relevance", "evidence_strength", "audience_fit", "brand_fit", "effort", "expected_value"];

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const router = useRouter();
  const { data, loading, error } = useApi<Detail>(`/api/campaigns/${id}`);
  const rep = useAction();
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  const c = data.campaign;
  const ev = Object.fromEntries(data.evidence.map((f) => [f.id, f]));

  return (
    <div>
      <PageHeader title={c.name} subtitle={c.objective}
        actions={<>
          <SyntheticBadge show={c.is_synthetic} label="Demo data" />
          {can.edit && <Button busy={rep.busy} onClick={async () => { const r = await rep.run(() => api.post<ReportSummary>(`/api/campaigns/${c.id}/report`)); if (r) router.push(`/reports/${r.id}`); }}>Generate report</Button>}
          {c.run_id && <Link href={`/agent/${c.run_id}`} className="rounded-lg border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">View agent run</Link>}
        </>} />
      {rep.error && <div className="mb-3"><Alert tone="bad">{rep.error}</Alert></div>}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Plan">
          <KeyValue items={[
            ["Audience", c.audience || "—"], ["Geography / language", `${c.geography || "—"} / ${c.language}`],
            ["Period", `${c.start_date || "—"} → ${c.end_date || "—"}`], ["Platforms", c.platforms.join(", ") || "—"],
            ["Pillars", c.pillars.join(" · ") || "—"], ["Creative direction", c.creative_direction || "—"],
            ["CTAs", c.ctas.join(" · ") || "—"], ["Measurement", c.measurement_plan || "—"],
            ["Success criteria", c.success_criteria.map((s) => `${titleCase(s.metric)}: ${s.comparator.replace(/_/g, " ")} ${s.target < 1 ? fmtPct(s.target, 0) : s.target}${s.variant ? ` (${s.variant} vs ${s.baseline})` : ""}`).join("; ") || "—"],
          ]} />
          {(c.risks.length > 0 || c.assumptions.length > 0) && (
            <div className="mt-3 grid gap-3 md:grid-cols-2 text-sm">
              <div><div className="mb-1 text-xs font-semibold uppercase text-muted">Risks</div><ul className="list-disc pl-4">{c.risks.map((r) => <li key={r}>{r}</li>)}</ul></div>
              <div><div className="mb-1 text-xs font-semibold uppercase text-muted">Assumptions</div><ul className="list-disc pl-4">{c.assumptions.map((r) => <li key={r}>{r}</li>)}</ul></div>
            </div>
          )}
        </Card>
        <Card title="Experiments">
          {data.experiments.length === 0 ? <p className="text-sm text-muted">None.</p> : data.experiments.map((e) => (
            <div key={e.id} className="mb-3 text-sm">
              <div className="flex flex-wrap items-center gap-1.5"><strong>{e.name}</strong><Badge tone={e.conclusion === "supported" ? "ok" : e.conclusion ? "warn" : "neutral"}>{e.conclusion || e.status}</Badge></div>
              <ul className="mt-1 text-xs text-muted">{e.variants.map((v) => <li key={v.label}>{v.label}: {v.description}</li>)}</ul>
              {e.learnings && <p className="mt-1 text-xs">{e.learnings}</p>}
            </div>
          ))}
          <Link href="/experiments" className="text-sm text-accent hover:underline">All experiments →</Link>
        </Card>
      </div>

      <Card className="mt-5" title="Campaign hypotheses" subtitle="Ranked by a weighted sum of 1–5 ratings. These are heuristic scores to make the choice transparent, not calibrated probabilities.">
        {data.hypotheses.length === 0 ? <p className="text-sm text-muted">No hypotheses (manual campaign).</p> : (
          <div className="space-y-4">
            {data.hypotheses.map((h) => (
              <div key={h.id} className={`rounded-lg border p-3 ${h.selected ? "border-accent bg-accent-soft/40" : "border-line"}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={h.selected ? "accent" : "neutral"}>#{h.rank}{h.selected ? " selected" : ""}</Badge>
                  <span className="text-sm font-semibold">{h.statement}</span>
                  <span className="ml-auto text-sm font-bold">{h.total_score.toFixed(2)}</span>
                </div>
                <div className="mt-2 grid gap-2 text-xs md:grid-cols-3">
                  <div><span className="text-muted">Mechanism:</span> {h.mechanism}</div>
                  <div><span className="text-muted">Uncertainty:</span> {h.uncertainty}</div>
                  <div><span className="text-muted">Validation:</span> {h.validation_method}</div>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {CRITERIA.map((k) => <Badge key={k} title={k}>{titleCase(k)} {h.scores[k] ?? "—"}</Badge>)}
                </div>
                {h.evidence_ids.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs">
                    {h.evidence_ids.map((eid) => ev[eid] && (
                      <li key={eid} className="flex flex-wrap items-center gap-1.5"><EvidenceBadge c={ev[eid].classification} /><SyntheticBadge show={ev[eid].is_synthetic} />
                        <span>{ev[eid].statement.slice(0, 160)}</span> <span className="text-muted">— <SourceLink f={ev[eid]} /></span></li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="mt-5" title="Content" actions={<Link href={`/calendar`} className="text-sm text-accent hover:underline">Calendar →</Link>}>
        {data.items.length === 0 ? <p className="text-sm text-muted">No content yet.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">Post</th><th className="pr-3">Type</th><th className="pr-3">Variant</th><th className="pr-3">Planned</th><th className="pr-3">Status</th><th>Checks</th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.items.map((i) => (
                  <tr key={i.id}>
                    <td className="py-1.5 pr-3"><Link href={`/content/${i.id}`} className="font-medium hover:underline">{i.title || i.caption.slice(0, 60)}</Link></td>
                    <td className="pr-3">{i.content_type}</td>
                    <td className="pr-3">{i.variant_label || "—"}</td>
                    <td className="pr-3 whitespace-nowrap text-muted">{fmtDate(i.published_at || i.scheduled_at || i.planned_at, can.tz)}</td>
                    <td className="pr-3"><ContentStatusBadge status={i.status} /></td>
                    <td>{i.validation ? (i.validation.ok ? <Badge tone="ok">pass</Badge> : <Badge tone="bad">{i.validation.failures} fail</Badge>) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {(data.recommendations.length > 0 || data.reports.length > 0) && (
        <div className="mt-5 grid gap-5 md:grid-cols-2">
          <Card title="Recommendations">
            {data.recommendations.map((r) => <div key={r.id} className="mb-2 text-sm"><strong>{r.title}</strong><p className="text-muted">{r.detail}</p></div>)}
          </Card>
          <Card title="Reports">
            {data.reports.map((r) => <div key={r.id}><Link href={`/reports/${r.id}`} className="text-sm text-accent hover:underline">{r.title} · {fmtDate(r.created_at, can.tz)}</Link></div>)}
          </Card>
        </div>
      )}
    </div>
  );
}
