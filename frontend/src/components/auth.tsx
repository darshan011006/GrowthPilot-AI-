"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrf } from "@/lib/api";
import type { AuthState } from "@/lib/types";

interface AuthCtx {
  state: AuthState | null;
  refresh: () => Promise<AuthState | null>;
}

const Ctx = createContext<AuthCtx>({ state: null, refresh: async () => null });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null);
  const refresh = useCallback(async () => {
    try {
      const s = await api.get<AuthState>("/api/auth/state");
      setCsrf(s.csrf || "");
      setState(s);
      return s;
    } catch {
      setState(null);
      return null;
    }
  }, []);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api.get<AuthState>("/api/auth/state")
        .then((s) => {
          if (!alive) return;
          setCsrf(s.csrf || "");
          setState(s);
        })
        .catch(() => alive && setState(null));
    load();
    window.addEventListener("gp:unauthenticated", load);
    return () => {
      alive = false;
      window.removeEventListener("gp:unauthenticated", load);
    };
  }, []);
  return <Ctx.Provider value={{ state, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}

export function useCan() {
  const { state } = useAuth();
  const role = state?.role;
  return { edit: role === "owner" || role === "editor", own: role === "owner", tz: state?.workspace?.timezone || "UTC", mode: state?.mode };
}
