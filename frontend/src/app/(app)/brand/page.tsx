"use client";

import { useState } from "react";
import { useCan } from "@/components/auth";
import { FreshnessBadge, ImageKindBadge, PLATFORM_ORDER, PlatformChip, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Field, Input, ListInput, Loading, Modal, PageHeader, Tabs, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtPrice } from "@/lib/format";
import type { Asset, Brand, Persona, Product } from "@/lib/types";

type Tab = "profile" | "marketing" | "claims" | "personas" | "products" | "festivals" | "assets";

type WebsiteDraft = { name: string; website: string; description: string; positioning: string; content_pillars: string[];
  profile_sources: { field: string; source_url: string; retrieved_at: string; note: string }[];
  pages_scanned: { url: string; title: string }[]; text_preview: string; needs_user_confirmation: string[] };

function WebsiteSetup({ onSaved, brand }: { onSaved: () => void; brand: Brand | null }) {
  const [website, setWebsite] = useState("");
  const [draft, setDraft] = useState<WebsiteDraft | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const scan = useAction();
  const save = useAction();
  const runScan = async () => {
    setDraft(null); setWarnings([]);
    const r = await scan.run(() => api.post<{ draft: WebsiteDraft; warnings: string[] }>("/api/onboarding/scan-website", { website }));
    if (r) { setDraft(r.draft); setWarnings(r.warnings); }
  };
  const continueManually = () => {
    const normalized = website.trim().startsWith("http") ? website.trim() : `https://${website.trim()}`;
    let host = "";
    try { host = new URL(normalized).hostname.replace(/^www\./, ""); } catch { /* show validation below */ }
    if (!host) { scan.setError("Enter a valid website URL first."); return; }
    setDraft({ name: host.split(".")[0].replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      website: normalized, description: "", positioning: "", content_pillars: [], profile_sources: [],
      pages_scanned: [], text_preview: "", needs_user_confirmation: ["description", "audience", "voice", "goals", "claims"] });
  };
  const confirm = async () => {
    if (!draft) return;
    const existing = editable(brand);
    const r = await save.run(() => api.put("/api/brand", { ...existing,
      name: draft.name.trim(), website: draft.website, description: draft.description || existing.description,
      positioning: draft.positioning || existing.positioning,
      content_pillars: draft.content_pillars.length ? draft.content_pillars : existing.content_pillars,
      profile_sources: [...(brand?.profile_sources || []), ...draft.profile_sources],
      permitted_sources: [...new Set([...existing.permitted_sources, new URL(draft.website).hostname])],
    }));
    if (r) onSaved();
  };
  return <Card title="Set up your brand from its website" subtitle="We read a few public pages and prepare a draft. Review it before agents use it; no website password is needed.">
    <div className="flex flex-col gap-2 sm:flex-row"><Input aria-label="Business website" type="url" placeholder="https://yourbusiness.com" value={website} onChange={(e) => setWebsite(e.target.value)} />
      <Button variant="primary" busy={scan.busy} onClick={runScan} disabled={!website.trim()}>Scan website</Button></div>
    {brand?.catalogue_source?.kind === "poojaloka_store_api" && website.trim() && (() => {
      try {
        const host = new URL(website.trim().startsWith("http") ? website.trim() : `https://${website.trim()}`).hostname.toLowerCase().replace(/^www\./, "");
        if (host === "poojaloka.com" || host.endsWith(".poojaloka.com")) return null;
        return <p className="mt-2 text-xs text-muted">Confirming this website will disconnect the Poojaloka catalogue and archive its imported products.</p>;
      } catch { return null; }
    })()}
    {scan.error && <div className="mt-3 flex flex-wrap items-center gap-2"><Alert tone="bad">{scan.error}</Alert><Button size="sm" onClick={continueManually}>Continue setup manually</Button></div>}
    {warnings.length > 0 && <div className="mt-3"><Alert tone="info" title="Some pages were skipped">{warnings.join(" ")}</Alert></div>}
    {draft && <div className="mt-4 space-y-3 rounded-xl border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>Review the website draft</strong><Badge tone="warn">Confirm before use</Badge></div>
      <Field label="Suggested business name">{(id) => <Input id={id} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />}</Field>
      <Field label="Suggested description">{(id) => <Textarea id={id} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />}</Field>
      <Field label="Page topics / positioning">{(id) => <Textarea id={id} value={draft.positioning} onChange={(e) => setDraft({ ...draft, positioning: e.target.value })} />}</Field>
      <p className="text-xs text-muted">Scanned {draft.pages_scanned.length} pages: {draft.pages_scanned.map((p) => p.title || p.url).join(" · ")}</p>
      {draft.profile_sources.length > 0 && <details className="text-xs text-muted"><summary className="cursor-pointer">Show source evidence</summary><ul className="mt-2 space-y-1">{draft.profile_sources.map((s, i) => <li key={`${s.source_url}-${i}`}><a className="text-info underline" href={s.source_url} target="_blank" rel="noreferrer">{s.source_url}</a> — {s.note}</li>)}</ul></details>}
      {draft.text_preview && <details className="text-xs text-muted"><summary className="cursor-pointer">Preview extracted page text</summary><p className="mt-2 whitespace-pre-wrap">{draft.text_preview}</p></details>}
      <p className="text-xs text-muted">Please complete audience, brand voice, goals, approved claims, and connect social channels after saving.</p>
      {save.error && <Alert tone="bad">{save.error}</Alert>}
      <Button variant="primary" busy={save.busy} onClick={confirm} disabled={!draft.name.trim()}>{brand ? "Confirm website and save" : "Confirm and create brand profile"}</Button>
    </div>}
  </Card>;
}

type BrandEdit = Omit<Brand, "id" | "is_synthetic" | "logo_asset_id" | "profile_sources" | "catalogue_source" | "festivals" | "articles" | "updated_at">;
const EMPTY_BRAND: BrandEdit = {
  name: "", description: "", positioning: "", voice: "", tone: "", audience: "", location: "", goals: "", website: "",
  colors: [], visual_guidelines: "", approved_claims: [], restricted_claims: [], prohibited_messaging: [], constraints: "",
  permitted_sources: [], content_pillars: [], languages: [], marketing_objectives: [], platform_preferences: [],
  posting_constraints: {}, campaign_budget_usd: null, fonts: [],
};

function editable(b: Brand | null): BrandEdit {
  const out = { ...EMPTY_BRAND } as Record<string, unknown>;
  if (b) for (const k of Object.keys(EMPTY_BRAND)) out[k] = (b as unknown as Record<string, unknown>)[k] ?? out[k];
  return out as BrandEdit;
}

function BrandForm({ brand, onSaved, section }: { brand: Brand | null; onSaved: () => void; section: "profile" | "claims" | "marketing" }) {
  const can = useCan();
  const [b, setB] = useState<BrandEdit>(() => editable(brand));
  const save = useAction();
  const [ok, setOk] = useState(false);
  const set = (k: keyof typeof b) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setB({ ...b, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setOk(false);
    const r = await save.run(() => api.put("/api/brand", b));
    if (r) {
      setOk(true);
      onSaved();
    }
  };
  return (
    <form onSubmit={submit}>
      <Card>
        {section === "marketing" ? (
          <div className="grid gap-x-4 md:grid-cols-2">
            <Field label="Content pillars" hint="one per line; the agent plans around these">{() => <ListInput value={b.content_pillars} onChange={(v) => setB({ ...b, content_pillars: v })} rows={5} />}</Field>
            <Field label="Marketing objectives" hint="one per line">{() => <ListInput value={b.marketing_objectives} onChange={(v) => setB({ ...b, marketing_objectives: v })} rows={5} />}</Field>
            <Field label="Languages" hint="one per line; on-image text renders in English">{() => <ListInput value={b.languages} onChange={(v) => setB({ ...b, languages: v })} />}</Field>
            <Field label="Fonts" hint="from your site or brand kit">{() => <ListInput value={b.fonts} onChange={(v) => setB({ ...b, fonts: v })} />}</Field>
            <div className="md:col-span-2">
              <Field label="Platform preferences" hint="tick the platforms you use; order = priority">{() => (
                <div className="flex flex-wrap gap-3">
                  {PLATFORM_ORDER.map((p) => (
                    <label key={p} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={b.platform_preferences.includes(p)}
                      onChange={(e) => setB({ ...b, platform_preferences: e.target.checked ? [...b.platform_preferences, p] : b.platform_preferences.filter((x) => x !== p) })} />
                      <PlatformChip platform={p} withLabel /></label>
                  ))}
                </div>
              )}</Field>
            </div>
            <Field label="Posting times" hint="HH:MM, comma separated, workspace time zone">{(id) => <Input id={id} value={(b.posting_constraints.posting_times || []).join(", ")} onChange={(e) => setB({ ...b, posting_constraints: { ...b.posting_constraints, posting_times: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} placeholder="09:30, 19:00" />}</Field>
            <Field label="Max posts per day">{(id) => <Input id={id} type="number" min={1} max={10} value={b.posting_constraints.max_posts_per_day ?? ""} onChange={(e) => setB({ ...b, posting_constraints: { ...b.posting_constraints, max_posts_per_day: e.target.value ? Number(e.target.value) : undefined } })} />}</Field>
            <Field label="Posting notes">{(id) => <Input id={id} value={(b.posting_constraints.notes as string) || ""} onChange={(e) => setB({ ...b, posting_constraints: { ...b.posting_constraints, notes: e.target.value } })} />}</Field>
            <Field label="Default campaign budget" hint="USD, for AI and tool costs">{(id) => <Input id={id} type="number" min={0} step="0.5" value={b.campaign_budget_usd ?? ""} onChange={(e) => setB({ ...b, campaign_budget_usd: e.target.value === "" ? null : Number(e.target.value) })} />}</Field>
          </div>
        ) : section === "profile" ? (
          <div className="grid gap-x-4 md:grid-cols-2">
            <Field label="Brand name">{(id) => <Input id={id} required value={b.name} onChange={set("name")} />}</Field>
            <Field label="Location">{(id) => <Input id={id} value={b.location} onChange={set("location")} placeholder="Bengaluru, India" />}</Field>
            <div className="md:col-span-2"><Field label="Description" hint="facts only — the agent repeats these">{(id) => <Textarea id={id} value={b.description} onChange={set("description")} />}</Field></div>
            <Field label="Positioning">{(id) => <Textarea id={id} value={b.positioning} onChange={set("positioning")} />}</Field>
            <Field label="Audience">{(id) => <Textarea id={id} value={b.audience} onChange={set("audience")} />}</Field>
            <Field label="Voice">{(id) => <Textarea id={id} value={b.voice} onChange={set("voice")} />}</Field>
            <Field label="Tone">{(id) => <Textarea id={id} value={b.tone} onChange={set("tone")} />}</Field>
            <Field label="Goals">{(id) => <Textarea id={id} value={b.goals} onChange={set("goals")} />}</Field>
            <Field label="Visual guidelines">{(id) => <Textarea id={id} value={b.visual_guidelines} onChange={set("visual_guidelines")} />}</Field>
            <Field label="Website">{(id) => <Input id={id} type="url" value={b.website} onChange={set("website")} placeholder="https://" />}</Field>
            <Field label="Brand colours" hint="hex, comma separated">
              {(id) => (
                <div className="flex items-center gap-2">
                  <Input id={id} value={b.colors.join(", ")} onChange={(e) => setB({ ...b, colors: e.target.value.split(",").map((c) => c.trim()).filter(Boolean) })} />
                  {b.colors.map((c) => <span key={c} title={c} className="h-6 w-6 shrink-0 rounded border border-line" style={{ background: /^#[0-9a-f]{6}$/i.test(c) ? c : "transparent" }} />)}
                </div>
              )}
            </Field>
          </div>
        ) : (
          <div className="grid gap-x-4 md:grid-cols-2">
            <Field label="Approved claims" hint="exact wording, one per line">{() => <ListInput value={b.approved_claims} onChange={(v) => setB({ ...b, approved_claims: v })} rows={5} />}</Field>
            <Field label="Restricted claims" hint="need evidence + owner sign-off">{() => <ListInput value={b.restricted_claims} onChange={(v) => setB({ ...b, restricted_claims: v })} rows={5} />}</Field>
            <Field label="Prohibited messaging" hint="never allowed">{() => <ListInput value={b.prohibited_messaging} onChange={(v) => setB({ ...b, prohibited_messaging: v })} rows={5} />}</Field>
            <Field label="Business constraints">{(id) => <Textarea id={id} rows={5} value={b.constraints} onChange={set("constraints")} />}</Field>
            <Field label="Permitted research sources" hint="domains the agent may fetch, one per line">{() => <ListInput value={b.permitted_sources} onChange={(v) => setB({ ...b, permitted_sources: v })} />}</Field>
            <div className="text-sm text-muted">
              <p className="mb-2 font-semibold text-ink">How claims are checked</p>
              <p>Prices, dimensions and materials must match the product catalogue. Offers, delivery promises, stock statements, warranties and certifications must match an approved claim word for word (or a product&apos;s verified attributes). Content that fails can&apos;t be approved.</p>
            </div>
          </div>
        )}
        {save.error && <Alert tone="bad">{save.error}</Alert>}
        {ok && <Alert tone="ok">Saved.</Alert>}
        <div className="mt-3"><Button variant="primary" type="submit" busy={save.busy} disabled={!can.edit}>Save</Button></div>
      </Card>
    </form>
  );
}

function PersonaEditor({ personas, onChange }: { personas: Persona[]; onChange: () => void }) {
  const can = useCan();
  const [edit, setEdit] = useState<Partial<Persona> | null>(null);
  const act = useAction();
  const save = async () => {
    if (!edit) return;
    const body = { name: edit.name, description: edit.description || "", goals: edit.goals || "", pain_points: edit.pain_points || "", preferred_platforms: edit.preferred_platforms || [] };
    const r = await act.run(() => (edit.id ? api.put(`/api/brand/personas/${edit.id}`, body) : api.post("/api/brand/personas", body)));
    if (r) {
      setEdit(null);
      onChange();
    }
  };
  return (
    <Card title="Personas" actions={can.edit && <Button size="sm" onClick={() => setEdit({ name: "" })}>Add persona</Button>}>
      {personas.length === 0 ? <Empty title="No personas yet" /> : (
        <div className="grid gap-3 md:grid-cols-3">
          {personas.map((p) => (
            <div key={p.id} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex items-start justify-between gap-2"><strong>{p.name}</strong>
                {can.edit && <span className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setEdit(p)}>Edit</Button>
                  <Button size="sm" variant="ghost" onClick={async () => { await act.run(() => api.del(`/api/brand/personas/${p.id}`)); onChange(); }}>Delete</Button></span>}
              </div>
              <p className="mt-1 text-muted">{p.description}</p>
              {p.goals && <p className="mt-1"><span className="text-muted">Goals:</span> {p.goals}</p>}
              {p.pain_points && <p className="mt-1"><span className="text-muted">Pain points:</span> {p.pain_points}</p>}
            </div>
          ))}
        </div>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? "Edit persona" : "Add persona"}>
        {edit && (
          <div>
            <Field label="Name">{(id) => <Input id={id} value={edit.name || ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />}</Field>
            <Field label="Description">{(id) => <Textarea id={id} value={edit.description || ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />}</Field>
            <Field label="Goals">{(id) => <Textarea id={id} value={edit.goals || ""} onChange={(e) => setEdit({ ...edit, goals: e.target.value })} />}</Field>
            <Field label="Pain points">{(id) => <Textarea id={id} value={edit.pain_points || ""} onChange={(e) => setEdit({ ...edit, pain_points: e.target.value })} />}</Field>
            {act.error && <Alert tone="bad">{act.error}</Alert>}
            <Button variant="primary" busy={act.busy} onClick={save} className="mt-2">Save</Button>
          </div>
        )}
      </Modal>
    </Card>
  );
}

const EMPTY_PRODUCT = { sku: "", name: "", category: "", collection: "", description: "", price: "", currency: "INR", dimensions: "", materials: [] as string[], finishes: [] as string[], verified_attributes: {} as Record<string, string>, image_asset_id: null as number | null, is_active: true };

function ProductEditor({ products, assets, onChange }: { products: Product[]; assets: Asset[]; onChange: () => void }) {
  const can = useCan();
  const [edit, setEdit] = useState<(typeof EMPTY_PRODUCT & { id?: number }) | null>(null);
  const [attrs, setAttrs] = useState("");
  const act = useAction();
  const open = (p?: Product) => {
    const v = p ? { ...EMPTY_PRODUCT, ...p, price: p.price === null ? "" : String(p.price) } : { ...EMPTY_PRODUCT };
    setEdit(v);
    setAttrs(Object.entries(v.verified_attributes).map(([k, val]) => `${k}: ${val}`).join("\n"));
  };
  const save = async () => {
    if (!edit) return;
    const verified_attributes = Object.fromEntries(attrs.split("\n").map((l) => l.split(":")).filter((p) => p.length >= 2 && p[0].trim()).map(([k, ...v]) => [k.trim(), v.join(":").trim()]));
    const body = { ...edit, verified_attributes, price: edit.price || null };
    delete (body as { id?: number }).id;
    const r = await act.run(() => (edit.id ? api.put(`/api/products/${edit.id}`, body) : api.post("/api/products", body)));
    if (r) {
      setEdit(null);
      onChange();
    }
  };
  return (
    <Card title="Product catalogue" subtitle="Verified facts the agent may use. Anything not here can't appear in approved content." actions={can.edit && <Button size="sm" onClick={() => open()}>Add product</Button>}>
      {products.length === 0 ? <Empty title="No products yet">Add at least one product so the agent can write factual content.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-2 pr-3">Product</th><th className="pr-3">Price</th><th className="pr-3">Stock</th><th className="pr-3">Materials</th><th className="pr-3">Source & quality</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {products.map((p) => (
                <tr key={p.id} className="align-top">
                  <td className="py-2 pr-3"><div className="font-semibold">{p.name} <SyntheticBadge show={p.is_synthetic} label="Fictional" />{!p.is_active && <Badge tone="bad">inactive</Badge>}</div>
                    <div className="text-xs text-muted">{p.name_local && `${p.name_local} · `}{p.category}{p.collection && ` · ${p.collection}`}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1">{p.image_asset_id ? <Badge tone="ok">real photo stored</Badge> : <ImageKindBadge kind={p.image_kind} />}{Boolean(p.flags?.best_seller) && <Badge tone="info">best seller</Badge>}</div></td>
                  <td className="pr-3">{fmtPrice(p.price, p.currency)}{p.mrp !== null && p.mrp !== p.price && <div className="text-xs text-muted line-through" title="MRP shown by the source; discount wording needs an approved claim">{fmtPrice(p.mrp, p.currency)}</div>}{p.variants?.length > 1 && <div className="text-xs text-muted">{p.variants.length} variants</div>}</td>
                  <td className="pr-3">{p.stock === null ? "—" : p.stock}{p.allow_backorder && p.stock !== null && p.stock <= 0 && <div className="text-xs text-muted">back-order</div>}</td>
                  <td className="pr-3">{p.materials.join(", ") || "—"}<div className="text-xs text-muted">{p.dimensions || p.finishes.join(", ")}</div></td>
                  <td className="pr-3 text-xs"><div className="flex flex-wrap items-center gap-1"><FreshnessBadge f={p.freshness} />{p.source_url && <a className="text-info hover:underline" href={p.source_url} target="_blank" rel="noopener noreferrer">source ↗</a>}</div>
                    {p.data_quality?.filter((q) => q.code !== "description_template").map((q) => <div key={q.code} className={["price_suspicious", "possible_test_listing", "stock_negative"].includes(q.code) ? "text-bad" : "text-muted"} title={q.message}>• {q.code.replace(/_/g, " ")}</div>)}
                    {Object.entries(p.verified_attributes).filter(([k]) => k !== "material_source").map(([k, v]) => <div key={k}><span className="text-muted">{k}:</span> {v}</div>)}</td>
                  <td className="whitespace-nowrap">{can.edit && <><Button size="sm" variant="ghost" onClick={() => open(p)}>Edit</Button>
                    <Button size="sm" variant="ghost" onClick={async () => { if (confirm(`Delete ${p.name}?`)) { await act.run(() => api.del(`/api/products/${p.id}`)); onChange(); } }}>Delete</Button></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? "Edit product" : "Add product"} wide>
        {edit && (
          <div className="grid gap-x-4 md:grid-cols-2">
            <Field label="SKU">{(id) => <Input id={id} value={edit.sku} onChange={(e) => setEdit({ ...edit, sku: e.target.value })} />}</Field>
            <Field label="Name">{(id) => <Input id={id} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />}</Field>
            <Field label="Category">{(id) => <Input id={id} value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} placeholder="sofa" />}</Field>
            <Field label="Collection">{(id) => <Input id={id} value={edit.collection} onChange={(e) => setEdit({ ...edit, collection: e.target.value })} />}</Field>
            <Field label="Price" hint={edit.currency}>{(id) => <Input id={id} inputMode="decimal" value={edit.price} onChange={(e) => setEdit({ ...edit, price: e.target.value })} />}</Field>
            <Field label="Dimensions">{(id) => <Input id={id} value={edit.dimensions} onChange={(e) => setEdit({ ...edit, dimensions: e.target.value })} placeholder="W 210 × D 92 × H 84 cm" />}</Field>
            <Field label="Materials" hint="one per line">{() => <ListInput value={edit.materials} onChange={(v) => setEdit({ ...edit, materials: v })} />}</Field>
            <Field label="Finishes" hint="one per line">{() => <ListInput value={edit.finishes} onChange={(v) => setEdit({ ...edit, finishes: v })} />}</Field>
            <div className="md:col-span-2"><Field label="Description">{(id) => <Textarea id={id} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />}</Field></div>
            <Field label="Verified attributes" hint="key: value per line, e.g. warranty: 5 years on the frame">{(id) => <Textarea id={id} value={attrs} onChange={(e) => setAttrs(e.target.value)} />}</Field>
            <Field label="Product photo">{(id) => (
              <select id={id} className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm" value={edit.image_asset_id ?? ""} onChange={(e) => setEdit({ ...edit, image_asset_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">None</option>
                {assets.filter((a) => ["upload", "catalogue"].includes(a.source)).map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
              </select>
            )}</Field>
            {act.error && <div className="md:col-span-2"><Alert tone="bad">{act.error}</Alert></div>}
            <div className="md:col-span-2"><Button variant="primary" busy={act.busy} onClick={save}>Save product</Button></div>
          </div>
        )}
      </Modal>
    </Card>
  );
}

function AssetPanel({ assets, onChange }: { assets: Asset[]; onChange: () => void }) {
  const can = useCan();
  const up = useAction();
  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    form.append("alt_text", f.name.replace(/\.[a-z]+$/i, ""));
    const r = await up.run(() => api.upload("/api/assets", form));
    e.target.value = "";
    if (r) onChange();
  };
  return (
    <Card title="Images" subtitle="Upload real product photos (JPEG or PNG, up to 8 MB). Instagram publishing needs JPEG." actions={can.edit && (
      <label className="cursor-pointer rounded-lg border border-line px-3 py-1.5 text-xs font-semibold hover:bg-panel-2">Upload image<input type="file" accept="image/jpeg,image/png" className="sr-only" onChange={upload} /></label>
    )}>
      {up.error && <div className="mb-3"><Alert tone="bad">{up.error}</Alert></div>}
      {assets.length === 0 ? <Empty title="No images yet" /> : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {assets.map((a) => (
            <figure key={a.id} className="overflow-hidden rounded-lg border border-line">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={a.url} alt={a.alt_text || a.filename} className="aspect-[4/5] w-full bg-panel-2 object-cover" loading="lazy" />
              <figcaption className="p-1.5 text-[11px]"><div className="truncate">{a.filename}</div>
                {a.placeholder ? <Badge tone="demo">placeholder</Badge> : <Badge tone="ok">{a.content_type.replace("image/", "")} {a.width}×{a.height}</Badge>}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </Card>
  );
}

function CatalogueStatus({ brand, products, onChange }: { brand: Brand; products: Product[]; onChange: () => void }) {
  const can = useCan();
  const act = useAction();
  const [msg, setMsg] = useState<string | null>(null);
  const src = brand.catalogue_source || {};
  const sourceMatchesBrand = src.kind !== "poojaloka_store_api" || (() => {
    try {
      const host = new URL(brand.website).hostname.toLowerCase().replace(/^www\./, "");
      return host === "poojaloka.com" || host.endsWith(".poojaloka.com");
    } catch {
      return false;
    }
  })();
  const fresh = products.reduce<Record<string, number>>((m, p) => ({ ...m, [p.freshness?.state || "manual"]: (m[p.freshness?.state || "manual"] || 0) + 1 }), {});
  const flagged = products.filter((p) => p.data_quality?.some((q) => ["price_suspicious", "possible_test_listing", "stock_negative"].includes(q.code))).length;
  const photos = products.filter((p) => p.image_kind === "product_photo" || p.image_asset_id).length;
  const sync = async () => {
    const r = await act.run(() => api.post<{ created: number; updated: number; unchanged: number; note: string; snapshot: boolean }>("/api/catalogue/sync", {}));
    if (r) { setMsg(`${r.created} new, ${r.updated} updated, ${r.unchanged} unchanged.${r.note ? ` ${r.note}` : ""}`); onChange(); }
  };
  if (!src.kind || !sourceMatchesBrand) return null;
  return (
    <Card className="mb-4" title="Catalogue source" subtitle={src.label} actions={can.own && <Button size="sm" busy={act.busy} onClick={sync}>{src.snapshot ? "Reload / sync" : "Sync now"}</Button>}>
      <div className="flex flex-wrap gap-2 text-xs">
        {src.snapshot && <Badge tone="demo">Dated snapshot (real data, not live)</Badge>}
        <Badge>Last synced {fmtDate(src.last_synced_at, undefined)}</Badge>
        {Object.entries(fresh).map(([k, n]) => <Badge key={k} tone={k === "fresh" ? "ok" : k === "stale" ? "bad" : k === "aging" ? "warn" : "neutral"}>{n} {k}</Badge>)}
        <Badge tone={photos ? "ok" : "warn"}>{photos}/{products.length} with a real product photo</Badge>
        {flagged > 0 && <Badge tone="bad">{flagged} flagged — won&apos;t be promoted</Badge>}
        {src.catalogue_total && <Badge>{products.length} of {src.catalogue_total.toLocaleString("en-IN")} products imported</Badge>}
      </div>
      {src.image_audit && (
        <p className="mt-2 text-xs text-muted">Image audit at the source: {Object.entries(src.image_audit.stock_photo_hosts).map(([h, n]) => `${n.toLocaleString("en-IN")} stock images (${h})`).join(", ")}; {Object.entries(src.image_audit.own_upload_hosts).map(([h, n]) => `${n} own upload(s) (${h})`).join(", ")}. Stock images are never shown as the product — upload real photos to use them in posters.</p>
      )}
      {msg && <div className="mt-2"><Alert tone="ok">{msg}</Alert></div>}
      {act.error && <div className="mt-2"><Alert tone="bad">{act.error}</Alert></div>}
    </Card>
  );
}

function Festivals({ brand }: { brand: Brand }) {
  if (!brand.festivals?.length && !brand.articles?.length) return <Empty title="No festival guides or articles">These come from the brand&apos;s own site when a catalogue connector is set.</Empty>;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {brand.festivals.map((f) => (
        <Card key={f.slug} title={<span>{f.name} {f.nameKn && <span className="text-sm font-normal text-muted">{f.nameKn}</span>}</span>} subtitle="From the brand's own festival guide (source-reported)">
          <p className="text-sm">{f.importance}</p>
          <div className="mt-2 text-xs font-semibold uppercase text-muted">Items needed</div>
          <div className="mt-1 flex flex-wrap gap-1">{f.itemsNeeded.map((i) => <Badge key={i}>{i}</Badge>)}</div>
          {f.poojaVidhi && <p className="mt-2 text-xs text-muted">Pooja vidhi: {f.poojaVidhi}</p>}
          {brand.website && <a className="mt-2 inline-block text-xs text-info hover:underline" href={`${brand.website.replace(/\/$/, "")}/festivals/${f.slug}`} target="_blank" rel="noopener noreferrer">Source ↗</a>}
        </Card>
      ))}
      {brand.articles.length > 0 && (
        <Card title="Articles" subtitle="Used for devotional know-how posts">
          <ul className="space-y-2 text-sm">{brand.articles.map((a) => <li key={a.slug}><strong>{a.title}</strong><div className="text-muted">{a.excerpt}</div></li>)}</ul>
        </Card>
      )}
    </div>
  );
}

export default function BrandPage() {
  // This page only renders client-side (after the session check), so reading the hash here is safe.
  const [tab, setTab] = useState<Tab>(() => (typeof window !== "undefined" && window.location.hash === "#products" ? "products" : "profile"));
  const { data, loading, error, reload } = useApi<{ brand: Brand | null; personas: Persona[]; products: Product[] }>("/api/brand");
  const assets = useApi<Asset[]>("/api/assets?source=upload,catalogue,placeholder");
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  const brand = data?.brand ?? null;
  return (
    <div>
      <PageHeader title="Brand Brain" subtitle="Everything the agent knows about the brand. Agent runs load this first (as a frozen snapshot), and verification checks every post against it." actions={<>
        {brand && brand.colors.slice(0, 5).map((c) => <span key={c} title={c} className="h-6 w-6 rounded-full border border-line" style={{ background: c }} />)}
        {brand?.is_synthetic && <SyntheticBadge label="Fictional demo brand" />}</>} />
      <div className="mb-4"><WebsiteSetup brand={brand} onSaved={reload} /></div>
      {brand && brand.profile_sources?.length > 0 && tab === "profile" && (
        <details className="mb-4 rounded-xl border border-line bg-panel p-3 text-sm">
          <summary className="cursor-pointer font-semibold">Where this profile came from ({brand.profile_sources.length})</summary>
          <ul className="mt-2 space-y-1 text-xs">{brand.profile_sources.map((ps) => <li key={ps.field}><strong>{ps.field}:</strong> {ps.note} {ps.source_url ? <a className="text-info hover:underline" href={ps.source_url} target="_blank" rel="noopener noreferrer">source ↗</a> : <Badge tone="warn">suggestion, not a fact</Badge>} <span className="text-muted">{fmtDate(ps.retrieved_at, undefined, false)}</span></li>)}</ul>
        </details>
      )}
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "profile", label: "Profile" }, { id: "marketing", label: "Marketing" }, { id: "claims", label: "Claims & sources" },
        { id: "personas", label: "Personas", count: data?.personas.length }, { id: "products", label: "Catalogue", count: data?.products.length },
        { id: "festivals", label: "Festivals & articles", count: brand?.festivals?.length },
        { id: "assets", label: "Images", count: assets.data?.filter((a) => ["upload", "catalogue"].includes(a.source)).length },
      ]} />
      {!brand && tab !== "profile" && tab !== "claims" ? <Empty title="Create the brand profile first" /> : (
        <>
          {(tab === "profile" || tab === "claims" || tab === "marketing") && <BrandForm key={`${brand?.id ?? "new"}-${tab}`} brand={brand} section={tab} onSaved={reload} />}
          {tab === "festivals" && <Festivals brand={brand!} />}
          {tab === "products" && <CatalogueStatus brand={brand!} products={data!.products} onChange={reload} />}
          {tab === "personas" && <PersonaEditor personas={data!.personas} onChange={reload} />}
          {tab === "products" && <ProductEditor products={data!.products} assets={assets.data || []} onChange={reload} />}
          {tab === "assets" && <AssetPanel assets={assets.data || []} onChange={assets.reload} />}
        </>
      )}
    </div>
  );
}
