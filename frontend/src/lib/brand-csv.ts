// Brand facts are optional in catalogue exports. Keep inferred summaries explicit for review.
export function normalizeCsvHeader(value: string): string {
  return value.replace(/^\uFEFF/, "").replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

export function csvValue(headers: string[], cells: string[], ...keys: string[]): string {
  for (const key of keys) {
    const index = headers.indexOf(key);
    if (index >= 0 && cells[index]?.trim()) return cells[index].trim();
  }
  return "";
}

export function catalogueDescription(name: string, products: { name: string; category: string }[]): string {
  const categories = [...new Set(products.flatMap((p) => p.category.split(/[,|;]/))
    .map((s) => s.trim()).filter((s) => s && s !== "Product"))].slice(0, 6);
  const examples = [...new Set(products.map((p) => p.name.trim()).filter(Boolean))].slice(0, 4);
  if (!examples.length) return "";
  return `${name || "This brand"} offers ${categories.length ? categories.join(", ") : "the products in this catalogue"}. `
    + `The catalogue includes ${examples.join(", ")}.`;
}

export type ProfileSource = { field: string; source_url: string | null; retrieved_at: string; note: string };

// The API accepts at most 100 profile sources; repeated scans/imports must not push a save past that.
export function mergeProfileSources<T extends ProfileSource>(...groups: T[][]): T[] {
  const seen = new Map<string, T>();
  for (const s of groups.flat()) seen.set(`${s.field}|${s.source_url}|${s.note}`, s);
  return [...seen.values()].slice(-100);
}

// Notes written when a value was suggested rather than read from the site or CSV.
export function isInferredSource(s: ProfileSource): boolean {
  return /^(Suggested|Editorial suggestion|Generic ecommerce suggestion)/i.test(s.note);
}

export type FieldStatus = "extracted" | "inferred" | "missing";

export function fieldStatus(field: string, value: string | string[] | undefined, sources: ProfileSource[]): FieldStatus {
  if (Array.isArray(value) ? !value.length : !(value || "").trim()) return "missing";
  const own = sources.filter((s) => s.field === field);
  if (!own.length) return "inferred";
  return own.some((s) => !isInferredSource(s)) ? "extracted" : "inferred";
}
