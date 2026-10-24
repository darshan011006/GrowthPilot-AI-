"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useCan } from "@/components/auth";
import { EvidenceBadge, SourceLink, SyntheticBadge } from "@/components/domain";
import { Alert, Card, Empty, Input, Loading, PageHeader, Select, useApi } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import type { Finding } from "@/lib/types";

const CLASSES: [string, string][] = [
  ["", "All evidence types"], ["verified_observation", "Verified observation"], ["source_reported", "Source-reported"],
  ["inference", "Inference"], ["hypothesis", "Hypothesis"], ["unknown", "Unknown"],
];
const SOURCES: [string, string][] = [
  ["", "All sources"], ["web_search", "Web search"], ["website", "Website"], ["internal", "Built-in calendar"],
  ["analysis", "Gap analysis"], ["fixture", "Demo fixture"],
];

function ResearchInner() {
  const params = useSearchParams();
  const can = useCan();
  const [cls, setCls] = useState("");
  const [src, setSrc] = useState("");
  const [q, setQ] = useState("");
  const runId = params.get("run_id") || "";
  const qs = new URLSearchParams({ classification: cls, source_type: src, q, run_id: runId }).toString();
  const { data, loading, error } = useApi<Finding[]>(`/api/research/findings?${qs}`);

  return (
    <div>
      <PageHeader title="Research" subtitle="Every finding keeps its source, retrieval time and evidence type. Search snippets are source-reported, not verified facts; demo fixtures have no real source." />
      <Card className="mb-4">
        <div className="grid gap-3 md:grid-cols-3">
          <Select aria-label="Evidence type" value={cls} onChange={(e) => setCls(e.target.value)}>{CLASSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          <Select aria-label="Source" value={src} onChange={(e) => setSrc(e.target.value)}>{SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          <Input aria-label="Search findings" placeholder="Search statements…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {runId && <p className="mt-2 text-xs text-muted">Showing findings from run {runId.slice(0, 8)}…</p>}
      </Card>
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? (
        <Empty title="No findings yet">Ask the agent to research trends or plan a campaign.</Empty>
      ) : (
        <div className="space-y-3">
          {data.map((f) => (
            <Card key={f.id}>
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <EvidenceBadge c={f.classification} />
                <SyntheticBadge show={f.is_synthetic} />
                {f.topic && <span className="text-xs font-semibold text-muted">{f.topic}</span>}
                <span className="ml-auto text-xs text-muted">#{f.id} · retrieved {fmtDate(f.retrieved_at, can.tz)}</span>
              </div>
              <p className="text-sm text-ink">{f.statement}</p>
              {f.evidence_excerpt && f.evidence_excerpt !== f.statement && <blockquote className="mt-1 border-l-2 border-line pl-2 text-xs text-muted">{f.evidence_excerpt}</blockquote>}
              <div className="mt-1.5 text-xs">Source: <SourceLink f={f} /></div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ResearchPage() {
  return <Suspense fallback={<Loading />}><ResearchInner /></Suspense>;
}
