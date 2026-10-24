"use client";

import { Suspense, type ReactNode } from "react";
import { AuthProvider } from "@/components/auth";
import { AppShell } from "@/components/shell";
import { Loading } from "@/components/ui";

export function AppFrame({ children }: { children: ReactNode }) {
  // The shell reads the URL (usePathname), which is runtime data on dynamic routes, so it streams in.
  return (
    <AuthProvider>
      <Suspense fallback={<Loading />}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </AuthProvider>
  );
}
