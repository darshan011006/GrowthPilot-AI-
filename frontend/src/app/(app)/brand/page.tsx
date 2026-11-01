"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth, useCan } from "@/components/auth";
import { FreshnessBadge, ImageKindBadge, PLATFORM_ORDER, PlatformChip, SyntheticBadge } from "@/components/domain";
import { Alert, Badge, Button, Card, Empty, Field, Input, ListInput, Loading, Modal, PageHeader, Tabs, Textarea, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { catalogueDescription, csvValue, fieldStatus, isInferredSource, mergeProfileSources, normalizeCsvHeader } from "@/lib/brand-csv";
import { fmtDate, fmtPrice } from "@/lib/format";
import type { Asset, Brand, Persona, Product } from "@/lib/types";

type Tab = "profile" | "marketing" | "claims" | "personas" | "products" | "festivals" | "assets";

type WebsiteProduct = { name: string; sku: string; category: string; description: string; price: string | null; currency: string;
  availability: string; image_urls: string[]; source_url: string; collection?: string; dimensions?: string;
  materials?: string[]; finishes?: string[]; verified_attributes?: Record<string, string> };
type WebsiteDraft = { name: string; website: string; description: string; positioning: string; location: string; audience: string;
  voice: string; tone: string; goals: string; visual_guidelines: string; colors: string[]; content_pillars: string[];
  profile_sources: { field: string; source_url: string; retrieved_at: string; note: string }[];
  pages_scanned: { url: string; title: string }[]; products: WebsiteProduct[]; text_preview: string; needs_user_confirmation: string[];
  languages?: string[]; marketing_objectives?: string[]; approved_claims?: string[]; restricted_claims?: string[];
  prohibited_messaging?: string[]; constraints?: string; fonts?: string[]; platform_preferences?: string[];
  posting_constraints?: Brand["posting_constraints"]; campaign_budget_usd?: number | null };
const productKey = (product: WebsiteProduct) => `${product.source_url}|${product.sku}|${product.name}`;

function csvRows(text: string): string[][] {
  const firstLine = text.split(/\r?\n/, 1)[0] || "";
  let delimiter = ",", best = -1;
  for (const candidate of [",", ";", "\t"]) {
    let count = 0, quotedHeader = false;
    for (const ch of firstLine) {
      if (ch === '"') quotedHeader = !quotedHeader;
      else if (ch === candidate && !quotedHeader) count++;
    }
    if (count > best) { delimiter = candidate; best = count; }
  }
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"' && quoted && text[i + 1] === '"') { cell += '"'; i++; }
    else if (ch === '"') quoted = !quoted;
    else if (ch === delimiter && !quoted) { row.push(cell.trim()); cell = ""; }
    else if ((ch === "\n" || ch === "\r") && !quoted) {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = []; cell = "";
    } else cell += ch;
  }
  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function WebsiteSetup({ onSaved, brand }: { onSaved: () => void; brand: Brand | null }) {
  const [website, setWebsite] = useState(brand?.website || "");
  const [draft, setDraft] = useState<WebsiteDraft | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [selectedProducts, setSelectedProducts] = useState<Set<string>>(new Set());
  const [platforms, setPlatforms] = useState<string[]>(brand?.platform_preferences || []);
  const [completion, setCompletion] = useState<{ products: number; photos: number } | null>(null);
  const scan = useAction();
  const save = useAction();
  const runScan = async () => {
    setWarnings([]); setCompletion(null);
    const r = await scan.run(() => api.post<{ draft: WebsiteDraft; warnings: string[] }>("/api/onboarding/scan-website", { website }));
    if (r) {
      const merged = draft ? {
        ...r.draft,
        ...Object.fromEntries((["name", "description", "positioning", "location", "audience", "voice", "tone", "goals", "visual_guidelines"] as const)
          .filter((key) => draft[key].trim() && !(r.draft[key].trim() && draft.profile_sources.some((s) => s.field === key && isInferredSource(s))
            && !draft.profile_sources.some((s) => s.field === key && !isInferredSource(s)))).map((key) => [key, draft[key]])),
        website: r.draft.website,
        colors: [...new Set([...r.draft.colors, ...draft.colors])],
        content_pillars: [...new Set([...r.draft.content_pillars, ...draft.content_pillars])],
        profile_sources: mergeProfileSources(r.draft.profile_sources, draft.profile_sources),
        pages_scanned: [...new Map([...r.draft.pages_scanned, ...draft.pages_scanned].map((page) => [page.url, page])).values()],
        products: [...new Map([...r.draft.products, ...draft.products].map((product) => [productKey(product), product])).values()].slice(0, 50),
        languages: [...new Set([...(r.draft.languages || []), ...(draft.languages || [])])],
        marketing_objectives: [...new Set([...(r.draft.marketing_objectives || []), ...(draft.marketing_objectives || [])])],
        approved_claims: [...new Set([...(r.draft.approved_claims || []), ...(draft.approved_claims || [])])],
        restricted_claims: [...new Set([...(r.draft.restricted_claims || []), ...(draft.restricted_claims || [])])],
        prohibited_messaging: [...new Set([...(r.draft.prohibited_messaging || []), ...(draft.prohibited_messaging || [])])],
        fonts: [...new Set([...(r.draft.fonts || []), ...(draft.fonts || [])])],
        platform_preferences: [...new Set([...(r.draft.platform_preferences || []), ...(draft.platform_preferences || [])])],
        posting_constraints: draft.posting_constraints || r.draft.posting_constraints,
        campaign_budget_usd: draft.campaign_budget_usd ?? r.draft.campaign_budget_usd,
        text_preview: [r.draft.text_preview, draft.text_preview].filter(Boolean).join("\n\n"),
        needs_user_confirmation: [...new Set([...r.draft.needs_user_confirmation, ...draft.needs_user_confirmation])],
      } : r.draft;
      setDraft(merged); setWarnings(r.warnings);
      setSelectedProducts(new Set(merged.products.map(productKey)));
    }
  };
  const continueManually = () => {
    const raw = website.trim();
    const normalized = raw ? (raw.startsWith("http") ? raw : `https://${raw}`) : (brand?.website || "");
    const host = (() => { try { return normalized ? new URL(normalized).hostname : ""; } catch { return ""; } })();
    if (normalized && !host) { scan.setError("Enter a valid website URL or continue with a CSV."); return; }
    const existing = editable(brand);
    setDraft({ name: brand?.name || host.replace(/^www\./, "").split(".")[0].replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      website: normalized, description: existing.description, positioning: existing.positioning, location: existing.location,
      audience: existing.audience, voice: existing.voice, tone: existing.tone, goals: existing.goals,
      visual_guidelines: existing.visual_guidelines, colors: existing.colors, content_pillars: existing.content_pillars,
      languages: existing.languages, marketing_objectives: existing.marketing_objectives,
      approved_claims: existing.approved_claims, restricted_claims: existing.restricted_claims,
      prohibited_messaging: existing.prohibited_messaging, constraints: existing.constraints, fonts: existing.fonts,
      platform_preferences: existing.platform_preferences, posting_constraints: existing.posting_constraints,
      campaign_budget_usd: existing.campaign_budget_usd,
      profile_sources: [], pages_scanned: [],
      products: [], text_preview: "", needs_user_confirmation: ["description", "audience", "voice", "goals", "claims"] });
    setSelectedProducts(new Set());
    setCompletion(null);
  };
  const importCsv = async (file?: File) => {
    if (!file) return;
    const rows = csvRows(await file.text());
    if (rows.length < 2) { scan.setError("CSV needs a header row and at least one product row."); return; }
    const headers = rows[0].map(normalizeCsvHeader);
    const get = (cells: string[], ...keys: string[]) => csvValue(headers, cells, ...keys);
    const hasProductName = headers.some((h) => ["name", "product_name", "item_name", "title"].includes(h));
    const hasBrandProfile = headers.some((h) => ["brand_name", "company_name", "business_name", "brand_description",
      "company_description", "business_description", "about_us", "brand_story", "brand_voice", "brand_tone",
      "brand_positioning", "brand_colors", "brand_website"].includes(h));
    if (!hasProductName && !hasBrandProfile) {
      scan.setError("CSV needs a name or product_name column. You can also include brand_name, brand_description, brand_voice, brand_colors, website, product_url, and image_url."); return;
    }
    const firstValue = (...keys: string[]) => rows.slice(1).map((cells) => get(cells, ...keys)).find((value) => value.trim()) || "";
    const splitList = (value: string) => value.split(/[|;\n]/).map((part) => part.trim()).filter(Boolean);
    const csvWebsite = firstValue("brand_website", "website", "site_url", "store_url", "company_website");
    const productUrl = firstValue("product_url", "source_url", "product_page");
    const rawWebsite = csvWebsite || website.trim() || draft?.website || brand?.website || "";
    let normalizedWebsite = "";
    try {
      if (rawWebsite) normalizedWebsite = new URL(rawWebsite.startsWith("http") ? rawWebsite : `https://${rawWebsite}`).toString();
      else if (productUrl) normalizedWebsite = new URL(productUrl).origin;
    } catch { normalizedWebsite = ""; }
    const current = draft || (() => {
      const existing = editable(brand);
      return { name: brand?.name || "", website: normalizedWebsite, description: existing.description,
        positioning: existing.positioning, location: existing.location, audience: existing.audience, voice: existing.voice,
        tone: existing.tone, goals: existing.goals, visual_guidelines: existing.visual_guidelines, colors: existing.colors,
        content_pillars: existing.content_pillars, languages: existing.languages, marketing_objectives: existing.marketing_objectives,
        approved_claims: existing.approved_claims, restricted_claims: existing.restricted_claims,
        prohibited_messaging: existing.prohibited_messaging, constraints: existing.constraints, fonts: existing.fonts,
        platform_preferences: existing.platform_preferences, posting_constraints: existing.posting_constraints,
        campaign_budget_usd: existing.campaign_budget_usd,
        profile_sources: [], pages_scanned: [], products: [], text_preview: "",
        needs_user_confirmation: ["brand name", "audience", "brand voice", "approved claims"] } satisfies WebsiteDraft;
    })();
    const profileFields: [string, string, string[]][] = [
      ["name", firstValue("brand_name", "company_name", "business_name", "company", "brand", "vendor"), ["brand_name", "brand", "vendor"]],
      ["description", firstValue("brand_description", "company_description", "business_description", "brand_about", "about_brand", "about_us", "brand_story", "brand_overview"), ["brand_description", "company_description", "about_us", "brand_story"]],
      ["positioning", firstValue("brand_positioning", "positioning", "brand_promise"), ["brand_positioning", "positioning", "brand_promise"]],
      ["voice", firstValue("brand_voice", "voice", "tone_of_voice"), ["brand_voice", "voice", "tone_of_voice"]],
      ["tone", firstValue("brand_tone", "tone"), ["brand_tone", "tone"]],
      ["audience", firstValue("target_audience", "brand_audience", "audience"), ["target_audience", "brand_audience", "audience"]],
      ["location", firstValue("brand_location", "business_location", "location"), ["brand_location", "business_location", "location"]],
      ["goals", firstValue("brand_goals", "marketing_goals", "business_goals", "goals"), ["brand_goals", "marketing_goals", "business_goals", "goals"]],
      ["visual_guidelines", firstValue("visual_guidelines", "brand_visual_guidelines", "brand_palette", "color_palette"), ["visual_guidelines", "brand_visual_guidelines", "brand_palette", "color_palette"]],
      ["constraints", firstValue("constraints", "brand_constraints", "business_constraints"), ["constraints", "brand_constraints"]],
    ];
    const profile: Record<string, string> = {};
    const profile_sources = [...current.profile_sources];
    for (const [field, value, keys] of profileFields) {
      if (!value) continue;
      profile[field] = value;
      profile_sources.push({ field, source_url: normalizedWebsite || "", retrieved_at: new Date().toISOString(),
        note: `Imported from CSV columns ${keys.join("/")}; review before use.` });
    }
    const listProfile: [string, string[], string[]][] = [
      ["content_pillars", splitList(firstValue("content_pillars", "brand_pillars")), ["content_pillars", "brand_pillars"]],
      ["languages", splitList(firstValue("languages", "brand_languages")), ["languages", "brand_languages"]],
      ["marketing_objectives", splitList(firstValue("marketing_objectives", "brand_objectives")), ["marketing_objectives", "brand_objectives"]],
      ["approved_claims", splitList(firstValue("approved_claims")), ["approved_claims"]],
      ["restricted_claims", splitList(firstValue("restricted_claims")), ["restricted_claims"]],
      ["prohibited_messaging", splitList(firstValue("prohibited_messaging", "prohibited_claims")), ["prohibited_messaging", "prohibited_claims"]],
      ["fonts", splitList(firstValue("brand_fonts", "fonts")), ["brand_fonts", "fonts"]],
    ];
    const profileLists: Record<string, string[]> = {};
    for (const [field, values, keys] of listProfile) {
      if (!values.length) continue;
      profileLists[field] = values;
      profile_sources.push({ field, source_url: normalizedWebsite || "", retrieved_at: new Date().toISOString(),
        note: `Imported from CSV columns ${keys.join("/")}; review before use.` });
    }
    const colorText = firstValue("brand_colors", "brand_colour", "brand_color", "primary_color", "brand_palette_hex");
    const csvColors = colorText.split(/[,|;\s]+/).filter((color) => /^#[0-9a-f]{6}$/i.test(color)).slice(0, 8);
    const csvPlatforms = splitList(firstValue("platform_preferences", "preferred_platforms", "channels"))
      .map((p) => p.toLowerCase()).filter((p) => (PLATFORM_ORDER as string[]).includes(p));
    const budgetText = firstValue("campaign_budget_usd", "campaign_budget");
    const budgetValue = budgetText ? Number(budgetText) : NaN;
    let postingConstraints: Brand["posting_constraints"] | undefined;
    try {
      const rawConstraints = firstValue("posting_constraints");
      const parsed = rawConstraints ? JSON.parse(rawConstraints) : null;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) postingConstraints = parsed;
    } catch { /* Keep current constraints when the CSV value is not valid JSON. */ }
    const rawRows = rows.slice(1);
    const imported = rawRows.map((cells, index) => {
      const imageIndexes = headers.map((header, i) => ({ header, i })).filter(({ header }) =>
        /^(image|image_url|image_urls|image_src|photo|photo_url|photo_urls|images|photos)(?:_?\d+)?$/.test(header)).map(({ i }) => i);
      let image_urls = [...new Set(imageIndexes.flatMap((i) => (cells[i] || "").split(/[|;,\n]/).map((x) => x.trim()).filter(Boolean)))].slice(0, 8);
      const rowValue = (...keys: string[]) => get(cells, ...keys);
      let source_url = rowValue("product_url", "source_url", "product_page", "url", "external_url") || normalizedWebsite || "";
      try { if (source_url && normalizedWebsite) source_url = new URL(source_url, normalizedWebsite).toString(); } catch { source_url = ""; }
      try { if (normalizedWebsite) image_urls = image_urls.map((url) => new URL(url, normalizedWebsite).toString()); } catch { image_urls = []; }
      const attributesRaw = rowValue("verified_attributes", "attributes");
      let verified_attributes: Record<string, string> = {};
      try { const parsed = JSON.parse(attributesRaw); if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) verified_attributes = parsed; } catch { /* keep empty */ }
      return { name: rowValue("name", "product_name", "item_name", "title"), sku: rowValue("sku", "product_sku") || `csv-${index + 1}`,
        category: rowValue("category", "categories", "product_type"), description: rowValue("product_description", "description", "body_html", "short_description"),
        price: rowValue("price", "regular_price") || null, currency: rowValue("currency", "currency_code"),
        availability: rowValue("availability", "stock_status"), source_url, image_urls,
        collection: rowValue("collection", "collection_name"), dimensions: rowValue("dimensions", "size") ||
          [rowValue("length", "length_in"), rowValue("width", "width_in"), rowValue("height", "height_in")].filter(Boolean).join(" × "),
        materials: splitList(rowValue("materials", "material")), finishes: splitList(rowValue("finishes", "finish", "colour", "color")),
        mrp: rowValue("mrp", "compare_at_price") || null, stock: rowValue("stock", "quantity", "inventory_quantity") || null,
        allow_backorder: rowValue("allow_backorder", "backorder", "backorders_allowed"), variants: rowValue("variants"),
        name_local: rowValue("name_local", "local_name"),
        verified_attributes };
    }).filter((product) => product.name.trim());
    if (!imported.length && !hasBrandProfile) { scan.setError("No product rows with a name or brand profile fields were found in that CSV."); return; }
    const siteHost = (() => { try { return normalizedWebsite ? new URL(normalizedWebsite).hostname : ""; } catch { return ""; } })();
    const csvName = profile.name || current.name || siteHost.replace(/^www\./, "").split(".")[0].replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    if (!profile.description && !current.description && imported.length) {
      profile.description = catalogueDescription(csvName, imported);
      profile_sources.push({ field: "description", source_url: "", retrieved_at: new Date().toISOString(),
        note: "Suggested from CSV product names and categories; confirm the brand description before saving." });
      setWarnings(["This CSV has no brand description. A catalogue-based description is suggested below. Review the brand name, description, audience and design style before confirming."]);
    } else { setWarnings([]); }
    const products = [...new Map([...current.products, ...imported].map((p) => [productKey(p), p])).values()].slice(0, 50);
    setDraft({ ...current, ...profile, ...profileLists, name: csvName, website: normalizedWebsite, colors: csvColors.length ? csvColors : current.colors,
      visual_guidelines: profile.visual_guidelines || (colorText ? `${current.visual_guidelines} Brand palette from CSV: ${colorText}.`.trim() : current.visual_guidelines),
      platform_preferences: csvPlatforms.length ? csvPlatforms : current.platform_preferences,
      posting_constraints: postingConstraints || current.posting_constraints,
      campaign_budget_usd: Number.isFinite(budgetValue) && budgetValue >= 0 ? budgetValue : current.campaign_budget_usd,
      profile_sources: mergeProfileSources(profile_sources), products,
      text_preview: `Loaded ${imported.length} product rows from ${file.name}. Brand profile fields found: ${[...Object.keys(profile), ...Object.keys(profileLists), ...(csvColors.length ? ["colors"] : []), ...(csvPlatforms.length ? ["platform_preferences"] : []), ...(postingConstraints ? ["posting_constraints"] : [])].join(", ") || "none"}.` });
    setSelectedProducts(new Set(products.map(productKey)));
    if (csvPlatforms.length) setPlatforms(csvPlatforms);
    setWebsite(normalizedWebsite);
    setCompletion(null);
    scan.setError(null);
  };
  const confirm = async () => {
    if (!draft) return;
    const existing = editable(brand);
    const r = await save.run(async () => {
      await api.put("/api/brand", { ...existing,
      name: draft.name.trim(), website: draft.website, description: draft.description || existing.description,
      positioning: draft.positioning || existing.positioning, content_pillars: draft.content_pillars.length ? draft.content_pillars : existing.content_pillars,
      location: draft.location.trim() || existing.location, audience: draft.audience.trim() || existing.audience,
      voice: draft.voice.trim() || existing.voice, tone: draft.tone.trim() || existing.tone,
      goals: draft.goals.trim() || existing.goals, visual_guidelines: draft.visual_guidelines.trim() || existing.visual_guidelines,
      colors: draft.colors.length ? draft.colors : existing.colors,
      languages: draft.languages?.length ? draft.languages : existing.languages,
      marketing_objectives: draft.marketing_objectives?.length ? draft.marketing_objectives : existing.marketing_objectives,
      approved_claims: draft.approved_claims?.length ? draft.approved_claims : existing.approved_claims,
      restricted_claims: draft.restricted_claims?.length ? draft.restricted_claims : existing.restricted_claims,
      prohibited_messaging: draft.prohibited_messaging?.length ? draft.prohibited_messaging : existing.prohibited_messaging,
      constraints: draft.constraints || existing.constraints, fonts: draft.fonts?.length ? draft.fonts : existing.fonts,
      platform_preferences: platforms,
      posting_constraints: draft.posting_constraints || existing.posting_constraints,
      campaign_budget_usd: draft.campaign_budget_usd ?? existing.campaign_budget_usd,
      profile_sources: mergeProfileSources(brand?.profile_sources || [], draft.profile_sources),
      permitted_sources: [...new Set([...existing.permitted_sources, ...(draft.website ? [new URL(draft.website).hostname] : [])])],
      });
      const chosen = draft.products.filter((p) => selectedProducts.has(productKey(p)));
      const result = chosen.length ? await api.post<{ created: number; updated: number; photos_downloaded: number; warnings: string[] }>(
        "/api/onboarding/import-products", { website: draft.website || null, products: chosen }) :
        { created: 0, updated: 0, photos_downloaded: 0, warnings: [] };
      return result;
    });
    if (r) { setWarnings((prev) => [...prev, ...r.warnings]); setCompletion({ products: r.created + r.updated, photos: r.photos_downloaded }); onSaved(); }
  };
  const sampleGoal = draft ? `Create one Instagram product post for ${draft.name} using a confirmed product from the catalogue. Use only verified product facts and its real product photo when available. Do not publish.` : "";
  return <Card title="Import brand details and catalogue" subtitle="Start with a CSV, a public website, or both. Review the draft before it updates Brand Brain or adds products.">
    <div className="flex flex-col gap-2 sm:flex-row"><Input aria-label="Business website" type="url" placeholder="https://yourbusiness.com" value={website} onChange={(e) => setWebsite(e.target.value)} />
      <Button variant="primary" busy={scan.busy} onClick={runScan} disabled={!website.trim()}>Scan website</Button>
      <label className="inline-flex cursor-pointer items-center justify-center rounded-lg border border-line px-3 py-2 text-sm font-semibold hover:border-accent">Upload CSV<input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => { void importCsv(e.target.files?.[0]); e.target.value = ""; }} /></label>
    </div>
    <p className="mt-2 text-xs text-muted">CSV can include brand_name, brand_description, positioning, voice, tone, audience, goals, brand_colors, and product columns such as name, sku, category, description, price, materials, dimensions, image_url, and product_url. CSV rows can include image URLs; product photos are imported as catalogue photos, separate from Gemini-created post images.</p>
    {scan.error && <div className="mt-3 flex flex-wrap items-center gap-2"><Alert tone="bad">{scan.error}</Alert><Button size="sm" onClick={continueManually}>Continue setup manually</Button></div>}
    {warnings.length > 0 && <div className="mt-3"><Alert tone="info" title="Import notes">{warnings.join(" ")}</Alert></div>}
    {draft && <div className="mt-4 space-y-3 rounded-xl border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>Review your setup draft</strong><Badge tone="warn">Confirm before use</Badge></div>
      <div className="rounded-lg border border-line bg-panel-2 p-3" aria-label="Extraction status">
        <p className="mb-2 text-sm font-semibold">What was found</p>
        <div className="flex flex-wrap gap-2 text-xs">{([["description", "Description", draft.description], ["positioning", "Positioning", draft.positioning], ["audience", "Audience", draft.audience],
          ["voice", "Voice", draft.voice], ["tone", "Tone", draft.tone], ["visual_guidelines", "Visual guidance", draft.visual_guidelines], ["colors", "Colours", draft.colors],
          ["location", "Location", draft.location], ["goals", "Goals", draft.goals]] as [string, string, string | string[]][]).map(([key, label, value]) => {
          const status = fieldStatus(key, value, draft.profile_sources);
          return <Badge key={key} tone={status === "extracted" ? "ok" : status === "inferred" ? "warn" : "bad"}>{label}: {status === "extracted" ? "from source" : status === "inferred" ? "inferred — confirm" : "missing — add"}</Badge>;
        })}</div>
      </div>
      <Field label="Suggested business name">{(id) => <Input id={id} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />}</Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Location (from published business address)">{(id) => <Input id={id} value={draft.location} onChange={(e) => setDraft({ ...draft, location: e.target.value })} placeholder="Not found on public pages" />}</Field>
        <Field label="Website">{(id) => <Input id={id} value={draft.website} onChange={(e) => setDraft({ ...draft, website: e.target.value })} />}</Field>
      </div>
      <Field label="Suggested description">{(id) => <Textarea id={id} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />}</Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Positioning">{(id) => <Textarea id={id} value={draft.positioning} onChange={(e) => setDraft({ ...draft, positioning: e.target.value })} />}</Field>
        <Field label="Audience (suggestion)">{(id) => <Textarea id={id} value={draft.audience} onChange={(e) => setDraft({ ...draft, audience: e.target.value })} placeholder="Not enough public evidence; add your audience" />}</Field>
        <Field label="Voice (suggestion)">{(id) => <Textarea id={id} value={draft.voice} onChange={(e) => setDraft({ ...draft, voice: e.target.value })} />}</Field>
        <Field label="Tone (suggestion)">{(id) => <Textarea id={id} value={draft.tone} onChange={(e) => setDraft({ ...draft, tone: e.target.value })} />}</Field>
        <Field label="Goals (suggestion)">{(id) => <Textarea id={id} value={draft.goals} onChange={(e) => setDraft({ ...draft, goals: e.target.value })} />}</Field>
        <Field label="Visual guidelines (suggestion)">{(id) => <Textarea id={id} value={draft.visual_guidelines} onChange={(e) => setDraft({ ...draft, visual_guidelines: e.target.value })} />}</Field>
        <Field label="Brand colours — hex, comma separated">{(id) => <Input id={id} value={draft.colors.join(", ")} onChange={(e) => setDraft({ ...draft, colors: e.target.value.split(",").map((c) => c.trim()).filter(Boolean) })} placeholder="#111111, #f5f5f5" />}</Field>
      </div>
      <div className="rounded-lg border border-line bg-panel-2 p-3">
        <p className="mb-2 text-sm font-semibold">Suggestions are editable; confirm before agents use them.</p>
        <div className="mt-2"><span className="mr-2 text-xs text-muted">Channels to focus on:</span><div className="inline-flex flex-wrap gap-2">{PLATFORM_ORDER.map((p) => <label key={p} className="flex cursor-pointer items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs"><input type="checkbox" checked={platforms.includes(p)} onChange={(e) => setPlatforms(e.target.checked ? [...platforms, p] : platforms.filter((x) => x !== p))} /><PlatformChip platform={p} withLabel /></label>)}</div></div>
      </div>
      <div className="rounded-lg border border-line p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold">Products found</p><p className="text-xs text-muted">We use structured facts published by your site; select what should enter the catalogue.</p></div><Badge>{draft.products.length} found</Badge></div>
        {draft.products.length === 0 ? <p className="text-sm text-muted">No structured product listings were found. Add a product CSV or continue with an empty catalogue and add products later.</p> : (
          <div className="max-h-80 space-y-2 overflow-y-auto">{draft.products.map((p) => {
            const key = productKey(p);
            return <label key={key} className="flex cursor-pointer gap-3 rounded-lg border border-line p-2.5 hover:border-accent">
              <input type="checkbox" className="mt-1" checked={selectedProducts.has(key)} onChange={(e) => setSelectedProducts((current) => { const next = new Set(current); if (e.target.checked) next.add(key); else next.delete(key); return next; })} />
              {p.image_urls[0] && <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={p.image_urls[0]} alt="" referrerPolicy="no-referrer" className="h-16 w-16 rounded-md bg-panel-2 object-cover" />
              </>}
              <span className="min-w-0 flex-1"><span className="block font-medium">{p.name}</span><span className="block text-xs text-muted">{p.category || "Product"} · {p.price && Number.isFinite(Number(p.price)) ? (p.currency ? fmtPrice(Number(p.price), p.currency) : `${p.price} (currency not listed)`) : "Price not found"}{p.availability ? ` · ${p.availability}` : ""}</span><span className="block truncate text-xs text-muted">{p.source_url}</span></span>
            </label>;
          })}</div>
        )}
        <p className="mt-1 text-xs text-muted">Select products and photos to add to the catalogue. Use Import CSV above to add more rows.</p>
      </div>
      <p className="text-xs text-muted">Scanned {draft.pages_scanned.length} pages: {draft.pages_scanned.map((p) => p.title || p.url).join(" · ")}</p>
      {draft.profile_sources.length > 0 && <details className="text-xs text-muted"><summary className="cursor-pointer">Show source evidence</summary><ul className="mt-2 space-y-1">{draft.profile_sources.map((s, i) => <li key={`${s.field}-${s.source_url}-${i}`}>{s.source_url ? <><a className="text-info underline" href={s.source_url} target="_blank" rel="noreferrer">{s.source_url}</a> — </> : "CSV — "}{s.note}</li>)}</ul></details>}
      {draft.text_preview && <details className="text-xs text-muted"><summary className="cursor-pointer">Preview extracted page text</summary><p className="mt-2 whitespace-pre-wrap">{draft.text_preview}</p></details>}
      <p className="text-xs text-muted">Review factual details and add approved claims later. GrowthPilot won&apos;t invent prices, offers, or guarantees.</p>
      {save.error && <Alert tone="bad">{save.error}</Alert>}
      <div className="flex flex-wrap items-center gap-3"><Button variant="primary" busy={save.busy} onClick={confirm} disabled={!draft.name.trim()}>Confirm setup{selectedProducts.size ? ` · ${selectedProducts.size} products` : ""}</Button>{completion && <span className="text-sm text-muted">Setup saved · {completion.products} products · {completion.photos} photos imported</span>}{completion && completion.products > 0 && sampleGoal && <Link className="rounded-lg border border-accent/40 px-3 py-2 text-sm font-semibold text-accent hover:bg-accent-soft" href={`/agent?goal=${encodeURIComponent(sampleGoal)}`}>Create a sample post ↗</Link>}</div>
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
  const { refresh: refreshAuth } = useAuth();
  const { data, loading, error, reload } = useApi<{ brand: Brand | null; personas: Persona[]; products: Product[] }>("/api/brand");
  const assets = useApi<Asset[]>("/api/assets?source=upload,catalogue,placeholder");
  const brandSaved = () => { void reload(); void refreshAuth(); };
  if (loading && !data) return <Loading />;
  if (error) return <Alert tone="bad">{error}</Alert>;
  const brand = data?.brand ?? null;
  return (
    <div>
      <PageHeader title="Brand Brain" subtitle="Everything the agent knows about the brand. Agent runs load this first (as a frozen snapshot), and verification checks every post against it." actions={<>
        {brand && brand.colors.slice(0, 5).map((c) => <span key={c} title={c} className="h-6 w-6 rounded-full border border-line" style={{ background: c }} />)}
        {brand?.is_synthetic && <SyntheticBadge label="Fictional demo brand" />}</>} />
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
          {tab === "profile" && <div className="mb-4"><WebsiteSetup brand={brand} onSaved={brandSaved} /></div>}
          {(tab === "profile" || tab === "claims" || tab === "marketing") && <BrandForm key={`${brand?.id ?? "new"}-${brand?.updated_at}-${tab}`} brand={brand} section={tab} onSaved={brandSaved} />}
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
