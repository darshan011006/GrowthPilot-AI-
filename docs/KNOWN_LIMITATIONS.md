# Feature status and known limitations (as of 2026-10-24)

## 1. Implemented and tested
Exercised in the demo and covered by the automated suite (96 backend tests) and the browser end-to-end test.

* Orchestrator with six specialist roles, delegation events, 26 typed tools tagged with role and side-effect class.
* Persistent runs: per-step trace (role, effect, cost, evidence ids), pause/resume, cancel, retry from the failing
  step, automatic recovery after a worker crash without redoing work, step/token/cost/time limits.
* Budget gate: per-run, per-campaign, monthly and single-step thresholds; pauses for owner approval; usage records;
  search cache and per-run/per-day caps.
* Poojaloka catalogue from a dated snapshot with source URLs, retrieval times, freshness, data-quality flags and the
  rule that stock images are never used as product photos.
* Poster rendering (Pillow) at each platform's size with contrast, safe-area, text-fit, glyph and dimension checks;
  PNG/JPEG download; layout variations.
* Claim verification (prices incl. variants and MRP, offers, warranties, stock/delivery, certifications, health
  claims, materials, dimensions, test listings, stale prices), brand checks and platform checks for seven platforms.
* Platform variants with independent approval, scheduling and publication; partial failures tracked per platform.
* Approval bound to the exact text, platform and image bytes (hash); database check constraint; duplicate
  prevention; idempotent publishing; send-time re-checks.
* Learning loop: baselines, platform-scoped A/B evaluation, confidence levels, recommendations with owner-approved
  changes, reports.

## 2. Implemented, awaiting credentials
Built from current official docs and tested against mocked APIs; not yet run against the real service.

* **Gemini** (Interactions API): structured outputs and tool use, including thought-signature replay. Prompt quality,
  latency and real token costs are unmeasured.
* **Claude** (optional alternative).
* **Brave Search** (single and parallel queries, caching, caps).
* **Live Poojaloka catalogue sync and refresh from the app.** The snapshot itself was fetched for real from the
  public API on 2026-10-24; the in-app connector is tested with a mocked API.
* **Gemini image backgrounds** (optional; off by default).

## 3. Awaiting platform permissions or review
* **Instagram** (Instagram Login) and **Facebook Pages**: live adapters built and mock-tested. They need a Meta app,
  professional accounts / a Page, tester roles or App Review for the scopes, and a public HTTPS `BASE_URL`. Exact
  error codes, insight availability and Page insights in production are unverified. Facebook metrics are public counts
  only (reach is "not available").

## 4. Simulated / demo-only
* Publishing and metrics on all seven platforms in demo mode (demo adapters, labelled "simulated"/"synthetic").
* The two competitors and their references are fictional fixtures; no engagement figures are shown for them.
* Trend notes in demo mode are labelled fixtures; the Poojaloka festival guides and articles are real.
* The demo generator is template-based. Its "Festival offers" slot deliberately uses offer wording so the
  verification loop has something real to catch.

## 5. Not implemented
* Live adapters for **Pinterest, X, LinkedIn, YouTube and Threads** (specs and simulated adapters only).
* Video (reels, stories, YouTube uploads). YouTube variants are Shorts briefs and are never sent for publishing.
* **Kannada (or other complex-script) text on images**: Pillow here has no shaping engine (libraqm), so on-image
  text must be English; the renderer detects unsupported glyphs and refuses. Captions can be in Kannada.
* Paid promotion / ad campaigns (the approval request type exists; no ads API is wired).
* Competitor Instagram data (Business Discovery needs the Facebook Login variant); private competitor metrics are
  always "not available".
* An evaluation harness comparing the agent with a one-shot LLM baseline. No uplift claims are made.
* Autonomous execution of recommendations: changes are proposed and applied only after an owner approves.

## Data and product caveats
* **Poojaloka has almost no product photography**: 2,876 of 2,877 products use generic Pixabay stock images, and the
  one real upload is a test listing. Posters therefore use typographic product cards until real photos are uploaded.
* Many Poojaloka products show stock 0 (back-order allowed), some have suspicious prices (₹1), negative stock or a
  "delivery unavailable" flag with a delivery estimate. These are flagged, not corrected; flagged items aren't promoted.
* Product descriptions at the source are a generic template, so they're never quoted as claims.
* Brand voice, tone, audience and goals in the demo profile are GrowthPilot suggestions, marked as such.
* Festival dates come from the built-in calendar and should be confirmed locally; the store's festival pages have no
  dates.
* Posting times come from the brand profile (09:30 / 19:00 in the demo); they're a starting point, not learned.
* Experiment statistics are deliberately simple; small samples are usually "inconclusive", which is intended.
* The claim checker is rule-based: it can produce false positives and can't judge subjective claims. Wording quoted
  from the brand's own guides/articles is treated as sourced (not as a product-material claim).
* One brand per workspace in the UI (the data model supports several). No email sending, MFA or SSO.

## Infrastructure not exercised
* **PostgreSQL**: supported through SQLAlchemy/psycopg; the suite runs on SQLite.
* **Docker Compose / Dockerfiles**: written, never built here (no Docker installed).
* **GitHub Actions**: runs tests, lint, type check, build and dependency audits on push. Docker images aren't built.
* Rate limits are per process (no Redis). Asset storage is local disk (swap `AssetStore` for object storage).

## Security gaps
See docs/SECURITY.md → Known gaps.
