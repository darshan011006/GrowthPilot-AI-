# GrowthPilot AI — web app

Next.js 16 (App Router, Turbopack), Tailwind CSS 4, Recharts. Client-rendered dashboard that talks to the FastAPI
backend through the `/api/*` rewrite in `next.config.ts` (`BACKEND_URL`, default `http://127.0.0.1:8000`).

Run it from the repository root with `make dev` (API + web) or `make frontend` (web only). Checks: `npx eslint src`,
`npx tsc --noEmit`, `npm run build`. See the root README for everything else.
