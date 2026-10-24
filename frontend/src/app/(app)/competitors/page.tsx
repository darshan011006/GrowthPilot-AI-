"use client";

import { useMemo, useState } from "react";
import { useCan } from "@/components/auth";
import { SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Tabs, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Brand, Competitor, ContentItem } from "@/lib/types";

type View = "gallery" | "compare" | "manage";

function Compare({ comps }: { comps: Competitor[] }) {
  const brand = useApi<{ brand: Brand | null }>("/api/brand");
  const own = useApi<ContentItem[]>("/api/content?main_only=true");
  const rows = useMemo(() => {
    const obs = comps.flatMap((c) => (c.observations || []).map((o) => ({ ...o, comp: c.name })));
    const themes = new Map<string, { theirs: number; ours: number; formats: Set<string> }>();
    for (const o of obs) {
      const k = o.theme.toLowerCase();
      const t = themes.get(k) || { theirs: 0, ours: 0, formats: new Set<string>() };
      t.theirs += 1;
      t.formats.add(o.content_format);
      themes.set(k, t);
    }
    for (const i of own.data || []) {
      const k = (i.pillar || "unspecified").toLowerCase();
      const t = themes.get(k) || { theirs: 0, ours: 0, formats: new Set<string>() };
      t.ours += 1;
      themes.set(k, t);
    }
    return [...themes.entries()].sort((a, b) => b[1].theirs + b[1].ours - (a[1].theirs + a[1].ours));
  }, [comps, own.data]);
  const offerShare = (() => {
    const obs = comps.flatMap((c) => c.observations || []);
    if (!obs.length) return null;
    return obs.filter((o) => /sale|discount|offer|% off/i.test(`${o.theme} ${o.excerpt}`)).length / obs.length;
  })();
  const ourOffers = (own.data || []).filter((i) => /offer|sale|discount/i.test(`${i.pillar} ${i.hook}`)).length;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card title={`${brand.data?.brand?.name || "Your brand"} vs competitors`} subtitle="Themes from observed competitor references next to your own main posts by pillar. Counts, not performance — competitor reach and saves aren't available.">
        {rows.length === 0 ? <p className="text-sm text-muted">No data yet.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">Theme / pillar</th><th className="pr-3">Competitors</th><th className="pr-3">You</th><th>Read</th></tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map(([k, t]) => (
                <tr key={k}>
                  <td className="py-1.5 pr-3 font-medium capitalize">{k}<div className="text-xs text-muted">{[...t.formats].join(", ")}</div></td>
                  <td className="pr-3"><span className="inline-block h-2 rounded bg-warm align-middle" style={{ width: `${t.theirs * 14}px` }} /> {t.theirs}</td>
                  <td className="pr-3"><span className="inline-block h-2 rounded bg-accent align-middle" style={{ width: `${t.ours * 14}px` }} /> {t.ours}</td>
                  <td className="text-xs">{t.theirs > 0 && t.ours === 0 ? <Badge tone="warn">they cover, you don&apos;t</Badge> : t.ours > 0 && t.theirs === 0 ? <Badge tone="ok">your opening</Badge> : <Badge>both</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Positioning notes">
        <ul className="space-y-2 text-sm">
          {offerShare !== null && <li><strong>{Math.round(offerShare * 100)}%</strong> of observed competitor references lead with a sale or discount; you have {ourOffers} offer-led main post(s). Offer wording needs an approved claim.</li>}
          <li>Gaps the agent found are recorded as inferences on the <a href="/research" className="text-accent hover:underline">Research</a> page with their evidence.</li>
          <li className="text-muted">Not available through the connected sources: reach, saves, demographics, ad spend, conversions, revenue.</li>
        </ul>
      </Card>
    </div>
  );
}

const NA = ["Reach", "Saves", "Audience demographics", "Ad spend", "Conversions", "Revenue"];

export default function CompetitorsPage() {
  const can = useCan();
  const { data, loading, error, reload } = useApi<Competitor[]>("/api/competitors");
  const [edit, setEdit] = useState<Partial<Competitor> | null>(null);
  const [view, setView] = useState<View>("gallery");
  const refs = (data || []).flatMap((c) => (c.observations || []).map((o) => ({ ...o, competitor: c })));
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
      <Tabs<View> value={view} onChange={setView} tabs={[{ id: "gallery", label: "Inspiration gallery", count: refs.length }, { id: "compare", label: "Side by side" }, { id: "manage", label: "Competitors", count: data?.length }]} />
      {loading && !data ? <Loading /> : error ? <Alert tone="bad">{error}</Alert> : !data?.length ? (
        <Empty title="No competitors yet">Add public competitor names and website URLs. With live search configured, the agent suggests public references.</Empty>
      ) : view === "gallery" ? (
        refs.length === 0 ? <Empty title="No references collected yet">Run “Analyse public competitor content…” in the Agent Command Centre.</Empty> : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {refs.map((o) => (
              <Card key={o.id} className="flex flex-col">
                <div className="mb-2 flex flex-wrap items-center gap-1.5"><Badge>{o.content_format}</Badge><span className="text-xs font-semibold">{o.competitor.name}</span><SyntheticBadge show={o.is_synthetic} label="Fixture" /></div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{o.theme}</div>
                <blockquote className="flex-1 border-l-2 border-warm pl-2 text-sm">“{o.excerpt}”</blockquote>
                <div className="mt-2 space-y-0.5 text-xs text-muted">
                  {o.cta && <div>CTA: <span className="text-ink">{o.cta}</span></div>}
                  <div>Engagement: {o.visible_engagement ? Object.entries(o.visible_engagement).map(([k, v]) => `${v} ${k} (publicly visible)`).join(", ") : "Not available through the connected source"}</div>
                  <div>{o.source_url ? <a className="text-info hover:underline" href={o.source_url} target="_blank" rel="noopener noreferrer nofollow">Source ↗</a> : "No real source (demo fixture)"} · observed {fmtDate(o.observed_at, can.tz, false)}</div>
                </div>
              </Card>
            ))}
          </div>
        )
      ) : view === "compare" ? <Compare comps={data} /> : (
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
