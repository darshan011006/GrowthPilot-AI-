import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin; /api/* is proxied to the FastAPI backend, so the
// session cookie stays same-origin (HttpOnly, SameSite=Lax) and no CORS is needed.
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
const devTunnelHost = process.env.GROWTHPILOT_TUNNEL_HOST || "ntsc-sticks-queensland-strength.trycloudflare.com";

const nextConfig: NextConfig = {
  // Permit the Cloudflare host to reach the dev server; this option is dev-server-only.
  allowedDevOrigins: [devTunnelHost],
  // Allow demo and live previews to run side by side without sharing Next's dev cache/lock.
  distDir: process.env.GROWTHPILOT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  // The dashboard is client-rendered behind a client-side session check, so pages can't render instantly
  // before that check. Validate only segments that opt in with `export const instant`.
  experimental: {
    instantInsights: { validationLevel: "manual-warning" },
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
