"use client";

import { useState } from "react";
import { useCan } from "@/components/auth";
import { SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Competitor } from "@/lib/types";

const NA = ["Reach", "Saves", "Audience demographics", "Ad spend", "Conversions", "Revenue"];

export default function CompetitorsPage() {
  const can = useCan();
  const { data, loading, error, reload } = useApi<Competitor[]>("/api/competitors");
  const [edit, setEdit] = useState<Partial<Competitor> | null>(null);
  const act = useAction();

  const save = async () => {
    if (!edit) return;
    const body = { name: edit.name || "", website: edit.website || "", instagram_url: edit.instagram_url || "", notes: edit.notes || "" };
    const r = await act.run(() => (edit.id ? api.put(`/api/competitors/${edit.id}`, body) : api.post("/api/competitors", body)));
    if (r) {
      setEdit(null);
      reload();
    }
  };

  return (
    <div>
      <PageHeader title="Competitor Radar" subtitle="Public competitor content from permitted sources: themes, formats, CTAs and engagement that's publicly visible. Used to find gaps, never to copy."
        actions={can.edit && <Button variant="primary" onClick={() => setEdit({})}>Add competitor</Button>} />
      <div className="mb-4"><Alert tone="info">
        GrowthPilot only uses public pages and authorised APIs, respects robots.txt and never bypasses logins or paywalls. Not available through the connected sources: {NA.join(", ").toLowerCase()}.
      </Alert></div>
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? (
        <Empty title="No competitors yet">Add public competitor names and website URLs.</Empty>
      ) : (
        <div className="space-y-4">
          {data.map((c) => (
            <Card key={c.id} title={<span className="flex items-center gap-2">{c.name} <SyntheticBadge show={c.is_synthetic} label="Fictional / synthetic" /></span>}
              subtitle={[c.website, c.instagram_url].filter(Boolean).join(" · ") || c.notes}
              actions={can.edit && <>
                <Button size="sm" variant="ghost" onClick={() => setEdit(c)}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={async () => { if (confirm(`Remove ${c.name}?`)) { await act.run(() => api.del(`/api/competitors/${c.id}`)); reload(); } }}>Remove</Button>
              </>}>
              {!c.observations?.length ? <p className="text-sm text-muted">No observations yet. Run “Analyse public competitor content…” in the Command Centre.</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">Theme</th><th className="pr-3">Format</th><th className="pr-3">Excerpt</th><th className="pr-3">CTA</th><th className="pr-3">Visible engagement</th><th>Published</th></tr></thead>
                    <tbody className="divide-y divide-line">
                      {c.observations.map((o) => (
                        <tr key={o.id} className="align-top">
                          <td className="py-1.5 pr-3 font-medium">{o.theme}</td>
                          <td className="pr-3"><Badge>{o.content_format}</Badge></td>
                          <td className="pr-3 text-muted">“{o.excerpt}”{o.source_url && <a className="ml-1 text-info hover:underline" href={o.source_url} target="_blank" rel="noopener noreferrer nofollow">source</a>}</td>
                          <td className="pr-3">{o.cta || "—"}</td>
                          <td className="pr-3">{o.visible_engagement ? Object.entries(o.visible_engagement).map(([k, v]) => `${v} ${k}`).join(", ") : <span className="text-muted">Not available</span>}</td>
                          <td className="whitespace-nowrap text-muted">{fmtDate(o.published_at, can.tz, false)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? "Edit competitor" : "Add competitor"}>
        {edit && (
          <div>
            <Field label="Name">{(id) => <Input id={id} value={edit.name || ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />}</Field>
            <Field label="Public website" hint="https://">{(id) => <Input id={id} value={edit.website || ""} onChange={(e) => setEdit({ ...edit, website: e.target.value })} />}</Field>
            <Field label="Instagram profile URL" hint="for reference; not scraped">{(id) => <Input id={id} value={edit.instagram_url || ""} onChange={(e) => setEdit({ ...edit, instagram_url: e.target.value })} />}</Field>
            <Field label="Notes">{(id) => <Textarea id={id} value={edit.notes || ""} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />}</Field>
            {act.error && <Alert tone="bad">{act.error}</Alert>}
            <Button variant="primary" busy={act.busy} onClick={save} className="mt-2">Save</Button>
          </div>
        )}
      </Modal>
    </div>
  );
}
