# GrowthPilot AI

**An evidence-backed marketing agent for furniture and home-interior brands.** It researches, finds a gap, forms
competing hypotheses, writes and validates on-brand content, waits for a person to approve it, publishes through
a verified adapter, measures what happened, and recommends the next experiment.

It's not a caption generator with a scheduler. Every claim in a post is checked against the product catalogue,
every research finding keeps its source and evidence type, every agent step is persisted and visible, and nothing
reaches a real account without explicit human approval of the exact version.

> **Two modes, kept separate.** **Demo** works with no credentials: a fictional brand (Aranya Living), labelled
> fixtures, a mock Instagram adapter and synthetic metrics. Nothing leaves your machine. **Live** uses Claude, Brave
> Search and the Instagram API with real data only, in a separate database. Live publishing is off by default.

## Quick start (demo, ~5 minutes)

Requirements: macOS/Linux, Python 3.11+, Node.js 24 (`brew install node@24`), make.

```bash
make setup     # Python venv + backend deps, npm ci for the frontend
make demo      # creates a demo login and loads the fictional demo brand (login saved to data/demo-login.txt)
make dev       # API on :8000 and web app on :3000 (the background worker runs inside the API)
```

Open http://localhost:3000, sign in with the credentials in `data/demo-login.txt`, then follow
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). No `.env` file is needed for demo mode; secret keys are generated
locally under `data/` (gitignored).

Prefer your own account? Skip `make demo`, open the app, register (the first user owns the workspace), and click
**Load demo data** on the Overview page.

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install backend and frontend dependencies |
| `make env` | Create `.env` from `.env.example` with fresh `SECRET_KEY`/`ENCRYPTION_KEY` (never overwrites) |
| `make demo` | Demo login + fictional brand, catalogue, competitors and synthetic campaign history |
| `make dev` | Run API + web app together |
| `make test` | Backend tests (pytest) + ruff, ESLint and TypeScript checks |
| `make build` | Production build of the frontend |
| `make e2e` | Browser end-to-end test of the demo flow (Playwright; needs `make dev` running) |
| `make migrate` | Apply database migrations (Alembic) |
| `make worker` | Run the background worker as its own process (set `RUN_WORKER_IN_PROCESS=false`) |

Database migrations run automatically on API start. Demo reset is in **Settings → Workspace & agent**.

## Going live

1. `make env`, then set `APP_MODE=live` in `.env`.
2. Add `LLM_API_KEY` (Anthropic) for the agent and content generation. API usage is billed separately from any
   Claude subscription.
3. Optional: `SEARCH_API_KEY` (Brave Search) for live web research.
4. Optional: Instagram. See [docs/API_INTEGRATIONS.md](docs/API_INTEGRATIONS.md) for the Meta app, professional
   account, redirect URI and public HTTPS URL requirements.
5. Restart with `make dev`. The **Integrations** page shows the true state of each integration, and the **Test**
   buttons check keys.
6. To post to a real account, also set `LIVE_PUBLISHING_ENABLED=true`. Every post still needs an owner's approval,
   explicit publish authorisation for that version, and a confirmation when scheduling.

Live mode uses `data/live.db` (or `DATABASE_URL`, e.g. PostgreSQL). A database is stamped with its mode and the app
refuses to open it in the other mode, so demo fixtures can never mix with real data.

## What's inside

| Area | Where |
|---|---|
| Agent (typed tool registry, demo planner, Claude tool-use planner, runner with budgets) | `backend/growthpilot/agent/` |
| 26 tools: research, competitors, planning, creative, validation, publishing, learning | `backend/growthpilot/agent/tools/` |
| Claims / brand / platform validation | `backend/growthpilot/services/validation.py` |
| Approval workflow, versioning, scheduling, duplicate prevention | `backend/growthpilot/services/content.py` |
| Publishing with idempotency and provider verification | `backend/growthpilot/services/publishing.py` |
| Instagram (Instagram Login), demo Instagram, signed webhook adapters | `backend/growthpilot/adapters/` |
| Web research (SSRF-guarded fetch, robots.txt, Brave Search) | `backend/growthpilot/research/` |
| Analytics, experiments (permutation test), reports | `backend/growthpilot/services/` |
| JSON API (FastAPI) | `backend/growthpilot/api/` |
| Web app (Next.js 16, Tailwind, Recharts) | `frontend/src/` |
| Demo fixtures | `backend/growthpilot/demo/fixtures.py` |

Docs: [Architecture](docs/ARCHITECTURE.md) · [Integrations](docs/API_INTEGRATIONS.md) · [Security](docs/SECURITY.md) ·
[Demo script](docs/DEMO_SCRIPT.md) · [Known limitations](docs/KNOWN_LIMITATIONS.md) · [Pitch](docs/PITCH.md) ·
[Tasks](TASKS.md)

## Verification status (last run 2026-10-24)

- Backend: 63 pytest tests pass (agent branching, tool schemas, validation, approvals, scheduling/time zones,
  idempotent publishing, OAuth state, token expiry/refresh, Instagram flow against a mocked Meta API, SSRF, CSRF,
  tenant isolation, secret redaction, demo/live separation, migrations from a clean database). Ruff is clean.
- Frontend: ESLint and `tsc` clean; `next build` succeeds (21 routes).
- Browser: `make e2e` passes in Chromium with no console errors: reset → login → agent run → re-plan → approve
  7 posts → auto-resume and schedule → simulated publish and verification → synthetic analytics → evaluation run
  → experiment conclusion → report.
- Dependency audit: `pip-audit` and `npm audit --omit=dev` report no known vulnerabilities.
- **Not verified:** any call to a real external API (Anthropic, Brave, Meta), PostgreSQL, Docker Compose, and
  GitHub Actions. See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `node: command not found` | `brew install node@24`; the Makefile adds `/opt/homebrew/opt/node@24/bin` to PATH automatically |
| Web app shows "Can't reach the GrowthPilot API" | Is the API running on :8000? `curl localhost:8000/api/health` |
| `Configuration error: Live mode requires SECRET_KEY` | Run `make env` (or set the key in `.env`) |
| "This database belongs to 'demo' mode…" | Use a separate `DATABASE_URL` per mode (defaults already differ) |
| Agent run says LLM unavailable | Live mode needs `LLM_API_KEY`; demo mode needs nothing |
| Instagram callback fails with "expired or invalid" | Start the connection again from Integrations; state links are single-use and expire after 10 minutes |
| Instagram publish fails "public HTTPS URL" | Set `BASE_URL` to a public HTTPS address (e.g. a tunnel) so Instagram can fetch images |
| Port already in use | `API_PORT=8001 WEB_PORT=3001 make dev` |
| Forgot the demo password | Delete `data/demo.db` and `data/demo-login.txt`, then `make demo` |
