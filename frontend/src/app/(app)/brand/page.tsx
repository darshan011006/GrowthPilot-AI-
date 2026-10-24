"use client";

import { useState } from "react";
import { useCan } from "@/components/auth";
import { SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Field, Input, ListInput, Loading, Modal, PageHeader, Tabs, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtPrice } from "@/lib/format";
import type { Asset, Brand, Persona, Product } from "@/lib/types";

type Tab = "profile" | "claims" | "personas" | "products" | "assets";

const EMPTY_BRAND: Omit<Brand, "id" | "is_synthetic" | "logo_asset_id"> = {
  name: "", description: "", positioning: "", voice: "", tone: "", audience: "", location: "", goals: "", website: "",
  colors: [], visual_guidelines: "", approved_claims: [], restricted_claims: [], prohibited_messaging: [], constraints: "",
  permitted_sources: [],
};

function BrandForm({ brand, onSaved, section }: { brand: Brand | null; onSaved: () => void; section: "profile" | "claims" }) {
  const can = useCan();
  const [b, setB] = useState({ ...EMPTY_BRAND, ...(brand || {}) });
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
        {section === "profile" ? (
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
            <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-2 pr-3">Product</th><th className="pr-3">Price</th><th className="pr-3">Dimensions</th><th className="pr-3">Materials</th><th className="pr-3">Verified attributes</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {products.map((p) => (
                <tr key={p.id} className="align-top">
                  <td className="py-2 pr-3"><div className="font-semibold">{p.name} <SyntheticBadge show={p.is_synthetic} label="Fictional" /></div><div className="text-xs text-muted">{p.sku} · {p.category}{p.collection && ` · ${p.collection}`}</div>{p.image_asset_id ? <Badge tone="ok">photo</Badge> : <Badge tone="neutral">no photo</Badge>}</td>
                  <td className="pr-3">{fmtPrice(p.price, p.currency)}</td>
                  <td className="pr-3">{p.dimensions || "—"}</td>
                  <td className="pr-3">{p.materials.join(", ") || "—"}<div className="text-xs text-muted">{p.finishes.join(", ")}</div></td>
                  <td className="pr-3 text-xs">{Object.entries(p.verified_attributes).map(([k, v]) => <div key={k}><span className="text-muted">{k}:</span> {v}</div>)}</td>
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
                {assets.filter((a) => a.source === "upload").map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
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

export default function BrandPage() {
  // This page only renders client-side (after the session check), so reading the hash here is safe.
  const [tab, setTab] = useState<Tab>(() => (typeof window !== "undefined" && window.location.hash === "#products" ? "products" : "profile"));
  const { data, loading, error, reload } = useApi<{ brand: Brand | null; personas: Persona[]; products: Product[] }>("/api/brand");
  const assets = useApi<Asset[]>("/api/assets");
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  const brand = data?.brand ?? null;
  return (
    <div>
      <PageHeader title="Brand Brain" subtitle="Everything the agent knows about the brand. Agent runs load this first, and validation checks every post against it." actions={brand?.is_synthetic && <SyntheticBadge label="Fictional demo brand" />} />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "profile", label: "Profile" }, { id: "claims", label: "Claims & sources" },
        { id: "personas", label: "Personas", count: data?.personas.length }, { id: "products", label: "Products", count: data?.products.length },
        { id: "assets", label: "Images", count: assets.data?.filter((a) => !a.placeholder).length },
      ]} />
      {!brand && tab !== "profile" && tab !== "claims" ? <Empty title="Create the brand profile first" /> : (
        <>
          {(tab === "profile" || tab === "claims") && <BrandForm key={`${brand?.id ?? "new"}-${tab}`} brand={brand} section={tab} onSaved={reload} />}
          {tab === "personas" && <PersonaEditor personas={data!.personas} onChange={reload} />}
          {tab === "products" && <ProductEditor products={data!.products} assets={assets.data || []} onChange={reload} />}
          {tab === "assets" && <AssetPanel assets={assets.data || []} onChange={assets.reload} />}
        </>
      )}
    </div>
  );
}
