"use client";

import { AuthProvider } from "@/components/auth";
import { ModeBanner } from "@/components/shell";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ModeBanner />
      <div className="grid min-h-[calc(100vh-2rem)] place-items-center px-4 py-10">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </AuthProvider>
  );
}
