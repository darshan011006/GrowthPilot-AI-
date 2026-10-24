"use client";

import {
  BarChart3,
  Bot,
  CalendarDays,
  ClipboardCheck,
  FileText,
  FlaskConical,
  LayoutDashboard,
  Megaphone,
  Menu,
  PenSquare,
  Plug,
  Radar,
  Search,
  Settings,
  Sofa,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { useAuth } from "./auth";
import { Loading } from "./ui";

const NAV: { section: string; items: { href: string; label: string; icon: typeof Bot }[] }[] = [
  { section: "", items: [{ href: "/", label: "Overview", icon: LayoutDashboard }, { href: "/agent", label: "Agent Command Centre", icon: Bot }] },
  { section: "Know", items: [{ href: "/brand", label: "Brand Brain", icon: Sofa }, { href: "/research", label: "Research", icon: Search }, { href: "/competitors", label: "Competitor Radar", icon: Radar }] },
  { section: "Plan & create", items: [{ href: "/campaigns", label: "Campaigns", icon: Megaphone }, { href: "/content", label: "Creative Studio", icon: PenSquare }, { href: "/calendar", label: "Calendar", icon: CalendarDays }, { href: "/approvals", label: "Approval Inbox", icon: ClipboardCheck }] },
  { section: "Learn", items: [{ href: "/analytics", label: "Analytics", icon: BarChart3 }, { href: "/experiments", label: "Experiments", icon: FlaskConical }, { href: "/reports", label: "Reports", icon: FileText }] },
  { section: "Admin", items: [{ href: "/integrations", label: "Integrations", icon: Plug }, { href: "/settings", label: "Settings", icon: Settings }] },
];

export function ModeBanner() {
  const { state } = useAuth();
  if (!state) return null;
  if (state.mode === "demo") {
    return (
      <div className="border-b border-line bg-demo-soft px-4 py-1.5 text-center text-xs font-semibold text-demo">
        DEMO MODE — fictional brand, labelled fixtures, simulated publishing and synthetic metrics. Nothing leaves this computer.
      </div>
    );
  }
  return (
    <div className={cx("border-b border-line px-4 py-1.5 text-center text-xs font-semibold", state.live_publishing_enabled ? "bg-bad-soft text-bad" : "bg-ok-soft text-ok")}>
      LIVE MODE — real AI, research and accounts. Live publishing is {state.live_publishing_enabled ? "ON: approved, authorised and scheduled posts will go out." : "OFF: nothing will be posted."}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { state, refresh } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [review, setReview] = useState(0);

  useEffect(() => {
    if (!state) return;
    if (!state.authenticated) router.replace(state.needs_setup ? "/register" : "/login");
  }, [state, router]);

  useEffect(() => {
    if (!state?.authenticated) return;
    let alive = true;
    const tick = () =>
      api.get<{ id: number }[]>("/api/content?status=in_review").then((r) => alive && setReview(r.length)).catch(() => {});
    tick();
    const t = setInterval(tick, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [state?.authenticated, path]);

  if (!state || !state.authenticated) return <Loading label="Checking your session…" />;

  const logout = async () => {
    await api.post("/api/auth/logout");
    await refresh();
    router.replace("/login");
  };

  return (
    <div className="flex min-h-screen flex-col">
      <ModeBanner />
      <div className="flex flex-1">
        <aside className={cx("fixed inset-y-0 left-0 z-30 w-64 transform border-r border-line bg-panel transition md:static md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
          <div className="flex h-full flex-col overflow-y-auto px-3 py-4">
            <Link href="/" className="mb-4 flex items-center gap-2 px-2 text-lg font-bold text-ink">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm text-accent-ink">G</span>
              GrowthPilot
            </Link>
            <nav aria-label="Main" className="flex-1 space-y-4">
              {NAV.map((group) => (
                <div key={group.section || "top"}>
                  {group.section && <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-muted">{group.section}</div>}
                  {group.items.map(({ href, label, icon: Icon }) => {
                    const active = href === "/" ? path === "/" : path.startsWith(href);
                    return (
                      <Link key={href} href={href} aria-current={active ? "page" : undefined} onClick={() => setOpen(false)}
                        className={cx("flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm", active ? "bg-accent-soft font-semibold text-accent" : "text-ink hover:bg-panel-2")}>
                        <Icon className="h-4 w-4" aria-hidden />
                        <span className="flex-1">{label}</span>
                        {href === "/approvals" && review > 0 && <span className="rounded-full bg-warn px-1.5 text-[11px] font-bold text-white">{review}</span>}
                      </Link>
                    );
                  })}
                </div>
              ))}
            </nav>
            <div className="mt-4 border-t border-line pt-3 text-sm">
              <div className="font-semibold text-ink">{state.user?.name}</div>
              <div className="text-xs text-muted">{state.workspace?.name} · {state.role}</div>
              <button onClick={logout} className="mt-2 text-xs font-semibold text-muted hover:text-ink">Sign out</button>
            </div>
          </div>
        </aside>
        {open && <button aria-label="Close menu" className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={() => setOpen(false)} />}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-line bg-panel px-4 py-2 md:hidden">
            <button aria-label="Open menu" onClick={() => setOpen(true)} className="rounded p-1 hover:bg-panel-2"><Menu className="h-5 w-5" /></button>
            <span className="font-bold">GrowthPilot</span>
          </div>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
