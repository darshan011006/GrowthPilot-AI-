"use client";

import { BarChart3, Bot, CalendarDays, ClipboardCheck, FileText, FlaskConical, Images, LayoutDashboard, Megaphone, Menu, PenSquare, Radar, Search, Settings, Store, Wallet, Zap, Activity, ChevronRight, Link2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { Run } from "@/lib/types";
import { cx } from "@/lib/format";
import { useAuth } from "./auth";
import { Loading } from "./ui";

const NAV = [
  { section: "", items: [{ href: "/", label: "Overview", icon: LayoutDashboard }, { href: "/agent", label: "AI Workspace", icon: Bot }, { href: "/calendar", label: "Content Calendar", icon: CalendarDays }, { href: "/content", label: "Content Library", icon: Images }, { href: "/campaigns", label: "Campaigns", icon: Megaphone }, { href: "/analytics", label: "Analytics", icon: BarChart3 }, { href: "/approvals", label: "Approvals", icon: ClipboardCheck }, { href: "/integrations", label: "Social Accounts", icon: Link2 }, { href: "/settings", label: "Settings", icon: Settings }] },
  { section: "More tools", items: [{ href: "/brand", label: "Brand Brain", icon: Store }, { href: "/research", label: "Research", icon: Search }, { href: "/competitors", label: "Competitor Radar", icon: Radar }, { href: "/assets", label: "Assets", icon: PenSquare }, { href: "/experiments", label: "Experiments", icon: FlaskConical }, { href: "/reports", label: "Reports", icon: FileText }, { href: "/usage", label: "Usage & Budgets", icon: Wallet }] },
];
const TITLES: Record<string, string> = { "/": "Mission Overview", "/agent": "AI Content Engine", "/calendar": "Content Calendar", "/content": "Content Library", "/campaigns": "Campaigns", "/analytics": "Analytics", "/approvals": "Approval Center", "/integrations": "Social Accounts", "/settings": "Settings", "/brand": "Brand Brain", "/research": "Research", "/competitors": "Competitor Radar", "/assets": "Asset Library", "/experiments": "Experiments", "/reports": "Reports", "/usage": "Usage & Budgets" };

export function ModeBanner() {
  const { state } = useAuth();
  if (!state) return null;
  return state.mode === "demo" ? (
    <div className="border-b border-line bg-demo-soft px-4 py-1.5 text-center text-xs font-semibold text-demo">DEMO MODE — demo data is labelled, external AI and publishing are disabled.</div>
  ) : (
    <div className={cx("border-b border-line px-4 py-1.5 text-center text-xs font-semibold", state.live_publishing_enabled ? "bg-bad-soft text-bad" : "bg-ok-soft text-ok")}>LIVE MODE — {state.live_publishing_enabled ? "publishing enabled; each exact version still needs owner approval and authorization." : "publishing is off."}</div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { state, refresh } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [review, setReview] = useState(0);
  const [runs, setRuns] = useState<Run[]>([]);

  useEffect(() => { if (state && !state.authenticated) router.replace(state.needs_setup ? "/register" : "/login"); }, [state, router]);
  useEffect(() => {
    if (!state?.authenticated) return;
    let alive = true;
    const tick = () => Promise.all([
      api.get<{ id: number }[]>("/api/content?status=in_review"),
      api.get<{ id: number }[]>("/api/approval-requests"),
      api.get<Run[]>("/api/agent/runs"),
    ]).then(([a, b, c]) => { if (alive) { setReview(a.length + b.length); setRuns(c.slice(0, 5)); } }).catch(() => {});
    tick(); const timer = setInterval(tick, 20000); return () => { alive = false; clearInterval(timer); };
  }, [state?.authenticated, path]);

  if (!state || !state.authenticated) return <Loading label="Checking your session…" />;
  const logout = async () => { await api.post("/api/auth/logout"); await refresh(); router.replace("/login"); };
  const activeRuns = runs.filter((r) => ["queued", "running", "paused", "awaiting_approval"].includes(r.status));

  return (
    <div className="min-h-screen bg-bg text-ink">
      <ModeBanner />
      <div className="flex min-h-[calc(100vh-30px)]">
        <aside className={cx("fixed inset-y-0 left-0 z-30 w-[250px] transform border-r border-line bg-[#0a100d] transition md:sticky md:top-[30px] md:h-[calc(100vh-30px)] md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
          <div className="flex h-full flex-col overflow-y-auto px-3 py-4">
            <Link href="/" className="mb-5 flex items-center gap-3 rounded-xl px-2 py-2 text-lg font-bold text-ink"><span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent text-accent-ink"><Zap className="h-6 w-6" /></span><span>GrowthPilot <span className="text-accent">AI</span><small className="block text-[10px] font-medium tracking-[.22em] text-muted">GROWTH OS</small></span></Link>
            <div className="mb-5 rounded-2xl border border-line bg-panel px-3 py-3 text-sm"><span className="block truncate font-medium">{state.workspace?.name || "Workspace"}</span><span className="mt-0.5 block text-[11px] text-muted">{state.workspace?.timezone || "Workspace timezone"}</span></div>
            <nav aria-label="Main" className="flex-1 space-y-5">
              {NAV.map((group) => <div key={group.section || "main"}>{group.section && <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[.18em] text-muted">{group.section}</div>}{group.items.map(({ href, label, icon: Icon }) => {
                const active = href === "/" ? path === "/" : path.startsWith(href);
                return <Link key={href} href={href} aria-current={active ? "page" : undefined} onClick={() => setOpen(false)} className={cx("relative mb-1 flex items-center gap-3 rounded-2xl px-3 py-3 text-[14px]", active ? "bg-accent-soft font-semibold text-accent before:absolute before:inset-y-3 before:left-0 before:w-1 before:rounded-full before:bg-accent" : "text-muted hover:bg-panel-2 hover:text-ink")}><Icon className="h-[19px] w-[19px]" aria-hidden /><span className="flex-1">{label}</span>{href === "/approvals" && review > 0 && <span className="rounded-full bg-bad px-1.5 text-[10px] font-bold text-white">{review}</span>}</Link>;
              })}</div>)}
            </nav>
            <div className="mt-4 rounded-xl border border-line bg-panel p-3"><div className="text-[10px] font-semibold uppercase tracking-[.18em] text-accent">{state.mode === "demo" ? "Demo workspace" : "Live workspace"}</div><div className="mt-1 truncate text-sm font-semibold">{state.user?.name}</div><div className="truncate text-xs text-muted">{state.workspace?.name} · {state.role}</div><button onClick={logout} className="mt-2 text-xs text-muted hover:text-ink">Sign out</button></div>
          </div>
        </aside>
        {open && <button aria-label="Close menu" className="fixed inset-0 z-20 bg-black/60 md:hidden" onClick={() => setOpen(false)} />}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 flex min-h-[76px] items-center gap-3 border-b border-line bg-[#090e0b]/95 px-4 backdrop-blur md:px-7">
            <button aria-label="Open menu" onClick={() => setOpen(true)} className="rounded-lg p-2 hover:bg-panel-2 md:hidden"><Menu className="h-5 w-5" /></button>
            <div className="min-w-0 flex-1"><div className="truncate text-xl font-bold tracking-tight">{TITLES[path] || Object.entries(TITLES).find(([route]) => route !== "/" && path.startsWith(`${route}/`))?.[1] || "GrowthPilot AI"}</div><p className="truncate text-sm text-muted">{path === "/" ? `Welcome back, ${state.user?.name?.split(" ")[0] || "there"} — here's your growth pulse` : state.workspace?.name || "Workspace"}</p></div>
            <span className="hidden rounded-2xl border border-line bg-panel px-4 py-3 text-sm text-ink sm:block">{state.workspace?.name || "Workspace"}</span>
            <Link href={activeRuns.length ? "/agent" : "/usage"} className="rounded-full border border-accent/30 bg-accent-soft px-4 py-3 text-sm font-semibold text-accent">{activeRuns.length ? `${activeRuns.length} active run${activeRuns.length === 1 ? "" : "s"}` : "Usage & limits"}</Link>
          </header>
          <div className="flex min-w-0 flex-1">
            <main className="w-full min-w-0 flex-1 px-4 py-5 md:px-7 md:py-7">{children}</main>
            <aside className="hidden w-[318px] shrink-0 border-l border-line bg-[#0b120e] p-4 xl:block">
              <div className="sticky top-[84px] flex max-h-[calc(100vh-100px)] flex-col"><div className="mb-4 flex items-center justify-between border-b border-line pb-4"><div><h2 className="text-lg font-semibold">Your AI Team</h2><p className="mt-0.5 flex items-center gap-1.5 text-sm text-muted"><Activity className="h-3.5 w-3.5 text-accent" />{activeRuns.length} active workflow{activeRuns.length === 1 ? "" : "s"}</p></div><span className="rounded-xl border border-line bg-panel p-2 text-accent"><Activity className="h-4 w-4" /></span></div>
                <div className="min-h-0 flex-1 space-y-2 overflow-auto">{runs.length ? runs.map((run) => <Link key={run.id} href={`/agent/${run.id}`} className="block rounded-xl border border-line bg-panel p-3 hover:border-accent/40"><div className="flex items-center justify-between gap-2"><span className="line-clamp-1 text-sm font-semibold">{run.intent || "Agent run"}</span><span className="shrink-0 rounded-full bg-panel-2 px-2 py-1 text-[9px] uppercase tracking-wider text-muted">{run.status.replaceAll("_", " ")}</span></div><p className="mt-2 line-clamp-2 text-xs leading-5 text-muted">{run.goal}</p><div className="mt-2 flex items-center justify-between text-[10px] text-muted"><span>{run.step_count} steps</span><span>{run.cost_usd.toFixed(3)} USD</span></div></Link>) : <div className="rounded-xl border border-dashed border-line p-4 text-sm text-muted">No agent runs yet. Start a workflow when you are ready.</div>}</div>
                <div className="mt-3 rounded-xl border border-line bg-[#080d0a] p-3"><div className="mb-2 text-[10px] font-semibold uppercase tracking-[.18em] text-muted">Quick links</div>{[["Start a workflow", "/agent"], ["Review approvals", "/approvals"], ["Check integrations", "/integrations"]].map(([label, href]) => <Link key={href} href={href} className="flex items-center justify-between border-b border-line/70 py-2 text-xs text-muted last:border-0 hover:text-accent">{label}<ChevronRight className="h-3.5 w-3.5" /></Link>)}</div>
              </div>
            </aside>
          </div>
        </div>
      </div>
    </div>
  );
}
