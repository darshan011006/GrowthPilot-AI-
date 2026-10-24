# Tasks

Legend: [x] done and verified locally · [~] implemented, verified only with mocks/tests · [ ] not done · [!] blocked on you

## Phase 0 — Environment & repository
- [x] Inspect machine: macOS 27 arm64, Python 3.11.7, Homebrew, Redis, SQLite, git, gh; no Node/Docker/Postgres
- [x] Install Node.js 24 LTS (Homebrew), project venv, frontend deps, Playwright Chromium (dev only)
- [x] Repo layout (`backend/`, `frontend/`, `docs/`, `scripts/`), `.gitignore`, `.env.example`, Makefile
- [x] Config validation per mode/env; demo/live database separation
- [x] Local commits (not pushed)

## Phase 1 — Foundation
- [x] FastAPI backend, SQLAlchemy models, Alembic migration (clean-state migrate + drift check tested)
- [x] Auth (first-user owner, invites), sessions, CSRF, roles, audit log
- [x] Fictional demo brand, catalogue, claims, personas, competitors, synthetic history; one-click reset
- [x] Next.js frontend: navigation, overview, all pages, loading/error/empty states, mobile layout

## Phase 2 — Working agent
- [x] Run state, persisted steps, budgets (steps/tokens/time), cancellation, retries, approval pause/auto-resume
- [x] 26 typed tools with schemas and permissions; mock usage labelled
- [x] Deterministic demo planner with real branching
- [~] Claude tool-use planner (tested with a scripted fake model)
- [~] Brave web research with provenance (mocked API)
- [x] Competitor analysis and gap finding (fixtures in demo; public website fetch in live, mocked)
- [x] Hypotheses + transparent ranking; campaign + A/B experiment + calendar
- [x] Creative briefs, captions, revision; labelled placeholder images
- [x] Claim, brand and platform validation; approval inbox; version-bound approval
- [x] Execution trace UI (polling real state)

## Phase 3 — Instagram
- [x] Checked current Meta docs (Instagram API with Instagram Login)
- [~] OAuth with state, encrypted tokens, refresh, account verification
- [~] Container → status → publish → verify; publishing limit; carousels; retries; idempotency; reconnect flow
- [!] Real-account verification: needs Meta app, professional IG account, tester role, public HTTPS `BASE_URL`

## Phase 4 — Analytics & adaptive strategy
- [x] Metric collection (synthetic in demo), definitions, freshness, missing data kept missing
- [~] Instagram insights (mocked)
- [x] Experiment evaluation (sample size, permutation test, association language)
- [x] Strategy revision → recommendations + next experiment; campaign reports (view/download)

## Phase 5 — Polish & delivery
- [x] Docs: README, ARCHITECTURE, API_INTEGRATIONS, SECURITY, DEMO_SCRIPT, KNOWN_LIMITATIONS, PITCH
- [x] Browser e2e test (Playwright), lint/type checks, production build, dependency audit
- [~] Docker Compose / Dockerfiles (written, not built: no Docker)
- [~] CI workflow (written, not run)
- [ ] Evaluation harness vs one-shot LLM baseline (needs LLM key)
- [ ] Pinterest adapter, image generation provider, reels/video publishing
- [ ] Facebook Login variant for competitor Business Discovery

## Needs you
- [!] `LLM_API_KEY` (Anthropic) to run the live agent
- [!] `SEARCH_API_KEY` (Brave) for live research
- [!] Meta app + professional Instagram account + public HTTPS URL for real publishing
- [!] Decide when to push to GitHub (not pushed)
