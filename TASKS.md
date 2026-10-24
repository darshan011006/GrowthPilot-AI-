# Tasks

Legend: [x] done and verified locally · [~] implemented, verified only with mocks/tests · [ ] not done · [!] blocked on you

## Phase 0–1 — Environment, foundation (done earlier)
- [x] Environment, repo, config validation, demo/live separation, auth/RBAC/CSRF/audit, migrations
- [x] Git commits; pushed to the private GitHub repo on request (later work is local until you say so)

## Phase A — Inspect (2026-10-24)
- [x] Reviewed the codebase, ran tests and the app
- [x] Inspected poojaloka.com: SPA backed by a public storefront API; 2,877 products; 2,876 use stock images

## Phase B — Agentic architecture
- [x] Orchestrator + six specialist roles; delegation events; shared brand snapshot
- [x] 26 typed tools with role and side-effect tags (incl. all names from the brief)
- [x] Persistent runs: pause/resume/cancel/retry; crash recovery without redoing work
- [x] Budget gate with owner approval; usage records; search cache and caps
- [x] Non-content approval requests (budget, strategy, paid promotion, account change)

## Phase C — Poojaloka experience
- [x] Catalogue connector (storefront API) + dated snapshot with provenance, freshness, data-quality flags
- [~] Live sync/refresh from the app (mocked API in tests; snapshot fetched for real)
- [x] Editable marketing profile (pillars, languages, objectives, platform preferences, posting constraints, budget)
- [x] Pillow poster renderer (brand fonts/colours, real photos only, typographic cards, checks, PNG/JPEG)
- [~] Optional Gemini AI backgrounds (mocked)
- [x] Platform variants, regenerate one variant, re-render with variations
- [x] UI: live timeline, platform previews, gallery, calendar drag & drop, inspiration gallery, side by side,
      asset library, version compare, usage dashboard, seven-platform integrations page

## Phase D — APIs
- [~] Gemini (Interactions API) planner + generator; connection test
- [~] Brave Search (parallel, cached, capped); connection test
- [!] Real keys: GEMINI_API_KEY, BRAVE_SEARCH_API_KEY

## Phase E — Distribution and learning
- [~] Instagram + Facebook Pages live adapters (mocked)
- [!] Meta app, professional IG account, Facebook Page, tester role / App Review, public HTTPS BASE_URL
- [x] Simulated adapters for all seven platforms; specs with limits/auth/eligibility
- [x] Per-platform status, partial failures, approval hash + DB constraint
- [x] Baselines, platform-scoped A/B, confidence, approvable recommendations
- [ ] Live adapters for Pinterest, X, LinkedIn, YouTube, Threads
- [ ] Video / reels; Kannada on-image text (needs libraqm); paid promotion APIs

## Phase F — Verify and document
- [x] 96 backend tests, ruff, ESLint, tsc, next build, browser e2e (Poojaloka flow)
- [x] README, ARCHITECTURE, API_INTEGRATIONS, DEPLOYMENT, SECURITY, DEMO_SCRIPT, KNOWN_LIMITATIONS
- [~] Docker Compose / PostgreSQL (written, not run here)
- [ ] Evaluation harness vs a one-shot LLM baseline (needs an LLM key)
