"use client";

import { useParams } from "next/navigation";
import { Markdown } from "@/components/markdown";
import { Alert, Card, Loading, PageHeader, useApi } from "@/components/ui";
import type { ReportSummary } from "@/lib/types";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { data, loading, error } = useApi<ReportSummary>(`/api/reports/${id}`);
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  if (!data) return null;
  return (
    <div>
      <PageHeader title={data.title} actions={<>
        <a href={`/api/reports/${id}/download`} className="rounded-lg border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">Download .md</a>
        <button onClick={() => window.print()} className="rounded-lg border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">Print / save as PDF</button>
      </>} />
      <Card><Markdown text={data.markdown || ""} /></Card>
    </div>
  );
}
