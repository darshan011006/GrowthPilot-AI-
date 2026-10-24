"use client";

import Link from "next/link";
import { useCan } from "@/components/auth";
import { SyntheticBadge } from "@/components/domain";
import { Alert, Card, Empty, Loading, PageHeader, useApi } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import type { ReportSummary } from "@/lib/types";

export default function ReportsPage() {
  const can = useCan();
  const { data, loading, error } = useApi<ReportSummary[]>("/api/reports");
  return (
    <div>
      <PageHeader title="Reports" subtitle="Campaign reports: objectives, hypotheses, evidence, content, approvals, publishing history, observed results and next steps." />
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? <Empty title="No reports yet">Generate one from a campaign, or ask the agent to evaluate results.</Empty> : (
        <Card>
          <ul className="divide-y divide-line">
            {data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                <Link href={`/reports/${r.id}`} className="font-medium hover:underline">{r.title}</Link>
                <span className="flex items-center gap-2 text-xs text-muted"><SyntheticBadge show={r.data_source === "synthetic" || r.data_source === "mixed"} /> {fmtDate(r.created_at, can.tz)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
