"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { cx } from "@/lib/format";

// ── data loading ─────────────────────────────────────────────────────────

export function useApi<T>(path: string | null) {
  const [nonce, setNonce] = useState(0);
  const [res, setRes] = useState<{ path: string | null; nonce: number; data: T | null; error: string | null }>({
    path: null, nonce: -1, data: null, error: null,
  });
  useEffect(() => {
    if (!path) return;
    let alive = true;
    api.get<T>(path)
      .then((data) => alive && setRes({ path, nonce, data, error: null }))
      .catch((e) => alive && setRes((r) => ({ ...r, path, nonce, error: errorMessage(e) })));
    return () => {
      alive = false;
    };
  }, [path, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const setData = useCallback((data: T) => setRes((r) => ({ ...r, data })), []);
  const loading = !!path && (res.path !== path || res.nonce !== nonce);
  return { data: res.data, error: res.path === path ? res.error : null, loading, reload, setData };
}

/** Wrap an async action with busy/error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <R,>(fn: () => Promise<R>): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}

// ── primitives ───────────────────────────────────────────────────────────

type Variant = "primary" | "secondary" | "ghost" | "danger" | "ok";
const variants: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:opacity-90 border-transparent",
  secondary: "bg-panel text-ink hover:bg-panel-2 border-line",
  ghost: "bg-transparent text-ink hover:bg-panel-2 border-transparent",
  danger: "bg-transparent text-bad hover:bg-bad-soft border-bad/40",
  ok: "bg-ok text-white hover:opacity-90 border-transparent",
};

export function Button({ variant = "secondary", size = "md", className, busy, children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg border font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variants[variant],
        className,
      )}
    >
      {busy && <Spinner className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}

export function LinkButton({ href, variant = "secondary", size = "md", children, className }: { href: string; variant?: Variant; size?: "sm" | "md"; children: ReactNode; className?: string }) {
  return (
    <Link href={href} className={cx("inline-flex items-center justify-center gap-1.5 rounded-lg border font-semibold transition", size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm", variants[variant], className)}>
      {children}
    </Link>
  );
}

export function Card({ children, className, title, actions, subtitle }: { children?: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; subtitle?: ReactNode }) {
  return (
    <section className={cx("rounded-xl border border-line bg-panel p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)]", className)}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

type Tone = "neutral" | "accent" | "ok" | "warn" | "bad" | "info" | "demo" | "warm";
const tones: Record<Tone, string> = {
  neutral: "bg-panel-2 text-muted",
  accent: "bg-accent-soft text-accent",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  demo: "bg-demo-soft text-demo",
  warm: "bg-warm-soft text-warm",
};

export function Badge({ tone = "neutral", children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold", tones[tone], className)}>
      {children}
    </span>
  );
}

export function Field({ label, hint, children, error }: { label: string; hint?: string; children: (id: string) => ReactNode; error?: string }) {
  const id = useId();
  return (
    <div className="mb-3">
      <label htmlFor={id} className="mb-1 block text-sm font-semibold text-ink">
        {label} {hint && <span className="font-normal text-muted">— {hint}</span>}
      </label>
      {children(id)}
      {error && <p className="mt-1 text-xs text-bad">{error}</p>}
    </div>
  );
}

const inputCls = "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm text-ink placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputCls, props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputCls, "min-h-[90px]", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputCls, props.className)} />;
}

export function Alert({ tone = "info", children, title }: { tone?: "info" | "ok" | "warn" | "bad" | "demo"; children: ReactNode; title?: string }) {
  const map = { info: "bg-info-soft text-info", ok: "bg-ok-soft text-ok", warn: "bg-warn-soft text-warn", bad: "bg-bad-soft text-bad", demo: "bg-demo-soft text-demo" };
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cx("rounded-lg px-3 py-2 text-sm", map[tone])}>
      {title && <div className="font-semibold">{title}</div>}
      {children}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("animate-spin", className || "h-4 w-4")} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted" role="status">
      <Spinner /> {label}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className={cx("mt-1 text-2xl font-bold", tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-ink")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-semibold", value === t.id ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink")}
        >
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 rounded-full bg-panel-2 px-1.5 text-[11px]">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} className={cx("m-auto w-[calc(100%-2rem)] rounded-xl border border-line bg-panel p-0 text-ink backdrop:bg-black/40", wide ? "max-w-3xl" : "max-w-lg")}>
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="font-semibold">{title}</h2>
        <button onClick={onClose} className="rounded px-2 text-muted hover:bg-panel-2" aria-label="Close">×</button>
      </div>
      <div className="max-h-[75vh] overflow-y-auto p-4">{open && children}</div>
    </dialog>
  );
}

/** Edit a list of short strings, one per line. */
export function ListInput({ value, onChange, placeholder, rows = 3 }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; rows?: number }) {
  const joined = value.join("\n");
  const [prev, setPrev] = useState(joined);
  const [text, setText] = useState(joined);
  if (joined !== prev) {
    // Reset local text when the value changes from outside (React's "derive state during render" pattern).
    setPrev(joined);
    setText(joined);
  }
  return (
    <Textarea
      rows={rows}
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => onChange(text.split("\n").map((s) => s.trim()).filter(Boolean))}
    />
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
