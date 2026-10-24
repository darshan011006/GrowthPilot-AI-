import { AppFrame } from "@/components/app-frame";

// Pages render only after the client-side session check, so navigations here are allowed to wait for it.
export const instant = false;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppFrame>{children}</AppFrame>;
}
