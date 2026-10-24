# GrowthPilot AI

**An agentic social media marketing team in one app.** Give it one business goal. An orchestrator delegates to six
specialists — Research, Strategy, Creative, Brand & Product Verification, Distribution and Performance Analyst —
that investigate the brand and its catalogue, form competing evidence-linked hypotheses, render real poster images,
check every claim against catalogue facts, adapt each post for up to seven platforms, wait for a person to approve
each exact version, schedule and verify publication, evaluate the results against a baseline and propose the next
experiment.

Every step is persisted and visible, every fact keeps its source and retrieval time, every paid call is estimated
and budgeted, and nothing reaches a real account without explicit human approval.

**Primary demo brand: [Poojaloka](https://poojaloka.com)**, a Bengaluru pooja-essentials store. The demo uses the
store's real catalogue (a dated snapshot of 40 products from its public storefront API), its own festival guides
and articles, and its colours and fonts. What can't be real without credentials is labelled: two fictional
competitors, fixture trend notes, synthetic metrics and simulated publishing.

> **Two modes, kept separate.** **Demo** needs no keys and makes no external or paid calls. **Live** uses Gemini
> (or Claude), Brave Search, the live Poojaloka storefront API and real platform adapters, in a separate database.
> Live publishing is off by default.

## Quick start (demo, ~5 minutes)

Requirements: macOS/Linux, Python 3.11+, Node.js 24 (`brew install node@24`), make.

```bash
make setup     # Python venv + backend deps (incl. Pillow), npm ci for the frontend
make demo      # demo login + the Poojaloka demo (login saved to data/demo-login.txt)
make dev       # API on :8000 and web app on :3000 (the background worker runs inside the API)
```

Open http://localhost:3000, sign in with the credentials in `data/demo-login.txt`, then follow
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). No `.env` is needed for demo mode.

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install backend and frontend dependencies |
| `make env` | Create `.env` from `.env.example` with fresh `SECRET_KEY`/`ENCRYPTION_KEY` (never overwrites) |
| `make demo` | Demo login + Poojaloka demo data (`python -m growthpilot demo-setup --brand aranya` for the fictional furniture brand) |
| `make dev` | Run API + web app together |
| `make test` | Backend tests (pytest) + ruff, ESLint, route types and TypeScript checks |
| `make build` | Production build of the frontend |
| `make e2e` | Browser end-to-end test of the Poojaloka flow (Playwright; needs `make dev` running) |
| `make migrate` | Apply database migrations (Alembic) |
| `make worker` | Run the background worker as its own process (set `RUN_WORKER_IN_PROCESS=false`) |
| `cd backend && .venv/bin/python -m growthpilot sync-catalogue` | Import the live Poojaloka catalogue (live mode) |

Migrations run automatically on API start. Demo reset (choose Poojaloka or Aranya) is in **Settings**.

## Going live

1. `make env`, then set `APP_MODE=live` in `.env`.
2. **Gemini** (`GEMINI_API_KEY`) runs the agent and writing. Claude (`LLM_API_KEY`) is an alternative
   (`LLM_PROVIDER=anthropic`). API usage is billed by the provider; consumer subscriptions don't include it.
3. **Brave Search** (`BRAVE_SEARCH_API_KEY`) for live research. Searches are cached for 24 h and capped per run/day.
4. Restart, open **Integrations** and press **Test connection** on each provider (one small request each).
5. Import the real catalogue: Brand Brain → Catalogue → **Sync now** (or `sync-catalogue` above).
6. Optional publishing: Instagram and Facebook Pages need a Meta app, professional accounts and a public HTTPS
   `BASE_URL` — see [docs/API_INTEGRATIONS.md](docs/API_INTEGRATIONS.md). To post for real, also set
   `LIVE_PUBLISHING_ENABLED=true`; every post still needs owner approval and explicit publish authorisation.
7. Set budgets in **Usage & Budgets** (per run, per month, single-step approval threshold, search caps).

Hosting: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Feature status (2026-10-24)

| Status | Features |
|---|---|
| **Implemented and tested** (demo + automated tests) | Orchestrator with six specialist roles and 26 typed, role- and effect-tagged tools; persistent runs with pause/resume/retry/cancel, crash recovery and budget-approval pauses; Poojaloka catalogue snapshot with provenance, freshness and data-quality flags; Pillow poster renderer (PNG/JPEG, platform sizes, contrast/safe-area/text-fit/glyph checks); claim, brand and platform verification with revision loop; per-platform variants with independent approval, scheduling and publication; approval bound to a hash of text + image bytes and a DB check constraint; duplicate prevention, idempotent publishing, partial-failure tracking; usage tracking, budgets, search cache and caps; platform-scoped A/B evaluation with baseline and confidence; recommendations with owner-approved changes; reports; all UI pages |
| **Implemented, awaiting credentials** (tested with mocked APIs) | Gemini planner and generator (Interactions API, thought-signature replay); Claude planner/generator; Brave Search (single + parallel); live Poojaloka catalogue sync and refresh; Gemini image backgrounds |
| **Awaiting platform permissions or review** | Instagram (Instagram Login) and Facebook Pages live adapters — built and mock-tested; need a Meta app, professional accounts, tester role or App Review, public HTTPS URL |
| **Simulated / demo-only** | Publishing and metrics on all seven platforms in demo mode; competitor references (fictional); trend fixture notes |
| **Not implemented** | Live adapters for Pinterest, X, LinkedIn, YouTube and Threads (specs + simulated adapters only); video/reels; Kannada text on images (captions can be Kannada); paid ad campaigns; evaluation harness vs a one-shot LLM baseline |

Details: [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Verification (last run 2026-10-24)

- Backend: 96 pytest tests pass — orchestration and state transitions, tool schemas, resumption and crash recovery,
  budget gates, research provenance, prompt-injection flags, product-fact verification, creative rendering and
  image sizes, versioning and approval invalidation (including image tampering), platform variants, duplicate
  prevention, partial publish failures, Gemini/Brave/Facebook/Instagram against mocked APIs (timeouts, auth
  errors, rate limits), catalogue ingestion, demo/live separation, secret handling, experiments. Ruff clean.
- Frontend: ESLint and `tsc` clean; `next build` succeeds.
- Browser: `make e2e` passes in Chromium with no console errors (reset → Poojaloka catalogue → multi-platform run →
  approve 28 platform versions → automatic scheduling → simulated publish + verification → asset library →
  analytics → evaluation → apply a recommendation → report → usage → mobile).
- **Not verified:** any real external API call (Gemini, Claude, Brave, Meta, live Poojaloka sync from the app),
  PostgreSQL and Docker Compose. The Poojaloka snapshot itself was fetched from the public storefront API on
  2026-10-24.

## What's inside

| Area | Where |
|---|---|
| Orchestrator, roles, runner (budgets, pause/resume, recovery) | `backend/growthpilot/agent/` |
| 26 tools by role: research, strategy, creative, verification, distribution, analyst | `backend/growthpilot/agent/tools/` |
| LLM providers (Gemini, Claude) | `backend/growthpilot/llm/` |
| Usage, prices, budgets | `backend/growthpilot/usage.py` |
| Catalogue connectors (Poojaloka API, snapshot) | `backend/growthpilot/catalogue/` |
| Poster renderer, fonts, image provider | `backend/growthpilot/creative/` |
| Platform specs (7) and adapters | `backend/growthpilot/platforms.py`, `backend/growthpilot/adapters/` |
| Verification, workflow, publishing, variants, analytics, experiments, reports | `backend/growthpilot/services/` |
| JSON API (FastAPI) | `backend/growthpilot/api/` |
| Web app (Next.js 16, Tailwind, Recharts) | `frontend/src/` |
| Demo data | `backend/growthpilot/demo/` |

Docs: [Architecture](docs/ARCHITECTURE.md) · [Integrations](docs/API_INTEGRATIONS.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Security](docs/SECURITY.md) · [Demo script](docs/DEMO_SCRIPT.md) ·
[Known limitations](docs/KNOWN_LIMITATIONS.md) · [Pitch](docs/PITCH.md) · [Tasks](TASKS.md)

## Troubleshooting

| Symptom | Fix |
|---|---|
| `node: command not found` | `brew install node@24`; the Makefile adds `/opt/homebrew/opt/node@24/bin` to PATH |
| "Can't reach the GrowthPilot API" | Is the API running on :8000? `curl localhost:8000/api/health` |
| `Configuration error: Live mode requires SECRET_KEY` | Run `make env` |
| "This database belongs to 'demo' mode…" | Use a separate `DATABASE_URL` per mode (defaults already differ) |
| Agent run says no LLM configured | Live mode needs `GEMINI_API_KEY` (or `LLM_API_KEY`); demo needs nothing |
| A run is waiting on "budget" | Approve or decline it in the Approval Inbox, or raise budgets in Usage & Budgets |
| Catalogue sync says "snapshot reloaded" | Demo mode makes no external calls; use live mode or `DEMO_ALLOW_CATALOGUE_SYNC=true` |
| Poster shows a "glyphs" failure | On-image text must be English (no complex-script shaping); captions can use Kannada |
| Instagram/Facebook publish fails "public HTTPS URL" | Set `BASE_URL` to a public HTTPS address so Meta can fetch images |
| Port already in use | `API_PORT=8001 WEB_PORT=3001 make dev` |
| Forgot the demo password | Delete `data/demo.db` and `data/demo-login.txt`, then `make demo` |
