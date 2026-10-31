# GrowthPilot AI: handover and implementation plan

**Status as of 1 Nov 2026.** For the engineer taking GrowthPilot from a working local product to a fully deployed
service that runs for any company. You'll get the API keys separately; never commit them.

**Your goal:** a hosted service where any company signs up and gets an AI marketing agent. The company gives a
website link or uploads a CSV. The agent researches, plans and writes the posts, and prompts the images. Designs are
made in Canva Pro. A person approves every post before it's published to Instagram and Facebook, and the agent then
learns from the results. Nothing below is optional unless it says so.

Read in this order: §1 status, §2 how it works today, §3 target pipeline, §4–§7 integrations, §8 any-company gaps,
§9 deployment, §10 work plan with acceptance criteria.

---

## 1. Where things stand

### Works and is tested
125 backend tests pass; ruff, ESLint and `tsc` are clean; CI runs in `.github/workflows/ci.yml`.

- **Accounts:** auth, workspaces, roles (owner, editor, viewer), invite-only registration once a workspace exists,
  CSRF protection and an audit log.
- **Two modes, kept apart:**
  - `demo` uses rules instead of AI, makes no external calls and uses fixture data (`data/demo.db`).
  - `live` uses the real AI model, search and platform adapters (`data/live.db`, or Postgres).
- **Agent:** an orchestrator with six specialist roles and 26 typed tools (§2.2). Runs are persistent: you can
  pause, resume, retry and recover from a crash. Each run has a budget gate, and usage and cost are recorded.
- **Brand onboarding:**
  - **Website scan:** reads the robots-allowed public pages of any site and pre-fills Brand Brain (name, description,
    positioning, audience, colours, sources). It extracts Schema.org products for review, then imports them with
    photos. Merged in PRs #2, #3, #5 and #6.
  - **CSV upload:** the Brand page parses a CSV in the browser and imports products. Required column: `name`.
    Optional: `sku, category, description, price, currency, image_url, product_url`.
  - **Catalogue rule:** a store-specific catalogue (Poojaloka) can never feed another brand (PR #4).
- **Creative brief:** `create_content_brief` writes a strictly validated `CreativeBrief` per post. It includes
  `image_policy`, `image_refs`, `required_text`, `claims_allowed`, `canva_query`, style, signals and data issues.
  Contract: `docs/creative-briefs/README.md` (PR #1).
- **Posters:** a local Pillow renderer makes JPEG posters and carousel slides at each platform's size. It checks
  claims on the image, contrast, safe margins and that stock photos aren't shown as products.
- **Checks and approvals:**
  - Every claim is checked against the catalogue; offers, prices, stock, health and other risky claims are blocked
    unless backed by data.
  - Approval is bound to the exact version and the image bytes (a database constraint enforces it).
  - Publishing needs `LIVE_PUBLISHING_ENABLED=true` and the owner's explicit authorisation.
- **Learning:** analytics baselines, A/B experiments within a platform, recommendations and reports.
- **Frontend:** Next.js 16 app covering overview, Brand Brain, campaigns, the agent run timeline, the calendar,
  content editing with seven-platform previews, the asset library, approvals, integrations, usage and settings.

### Built but never run against the real service
| Piece | State | What's missing |
|---|---|---|
| Gemini (Interactions API) | Real calls made once | The free tier allows 20 requests a day per model, so a full run doesn't fit. Billing is needed, or replace it with Groq (§5). |
| Brave Search | Real calls made | Rotate the key; it was once printed in a terminal log. |
| Instagram + Facebook Pages adapters | Implemented, mocked in tests | A real Meta app, a public HTTPS `BASE_URL`, and the first real post (§6). |
| PostgreSQL + Docker Compose | Written | Never run (Docker wasn't installed on the dev machine). |

### Not built
- **Groq provider:** `LLM_PROVIDER` only accepts `auto`, `gemini` or `anthropic` today. Setting `groq` stops the app
  from starting.
- **Canva integration:** no code is on GitHub. A teammate started local Canva work touching `content.py`,
  `models.py`, `worker.py`, `agent/tools/creative.py`, `frontend/src/lib/types.ts` and a migration. **Ask them to
  push it first** and build on it; §4 is the target design.
- **Image generation from prompts:** the brief has `canva_query`, but no image is generated from it yet.
- **Server-side CSV import with validation,** and connectors for Shopify and WooCommerce.
- **Production basics:** object storage for images, email (invites are copy-and-paste links today), password reset
  by email, monitoring, backups, and a shared rate-limit store when there are several API instances.

### Open PRs and branches
- **PR #7 `setup/one-command-start`:** `make start` takes a fresh clone to a running app, with a clear sign-in error
  when the API is down. Merge it first.
- **Old branches:** `codex/*` and `feature/creative-brief` are merged and can be deleted.

---

## 2. How it works today

### 2.1 Run it
```bash
make start          # after PR #7: deps, .env, DB, demo login, API :8000 + web :3000
make test           # backend tests + lint + frontend type-check
```
- **Demo login:** `data/demo-login.txt`.
- **Live mode:** set `APP_MODE=live` in `.env` (it uses a separate database), then register the first account at
  `/register`.
- **Each machine has its own database.** Accounts don't move between machines.

### 2.2 Agent roles and tools (`backend/growthpilot/agent/tools/`)
| Role | Tools |
|---|---|
| Research | `inspect_brand`, `retrieve_catalogue`, `search_web`, `inspect_website`, `analyse_trends`, `collect_competitor_references`, `identify_content_gaps` |
| Strategy | `create_campaign_plan`, `rank_campaign_ideas`, `estimate_campaign_cost` |
| Creative | `create_content_brief`, `generate_caption`, `generate_creative_asset` |
| Verification | `verify_product_facts`, `validate_creative` |
| Distribution | `check_platform_capabilities`, `prepare_schedule`, `create_platform_variant`, `request_human_approval`, `publish_approved_content`, `verify_publication` |
| Performance analyst | `retrieve_available_analytics`, `analyse_campaign_history`, `evaluate_experiment`, `recommend_next_action`, `generate_campaign_report` |

**Planners:**
- `agent/planner_demo.py` runs a fixed step list with branching (demo mode).
- `agent/planner_llm.py` lets the model choose tools in a loop (live mode). The conversation lives in
  `agent_runs.state`.
- `agent/runner.py` drives both. It handles budgets, retries (waits of 10, 20, 40 and 60 s on rate limits) and
  approval pauses.

**Text generation:** `agent/generation.py` provides `DemoGenerator` and `LLMGenerator`. The LLM version calls the
provider's `structured()` method with Pydantic schemas.

**LLM providers:** `llm/` has `gemini_llm.py` and `anthropic_llm.py`. Each implements `structured(system, prompt,
schema)` and `tool_turn(system, messages, tools)`. The conversation format follows Anthropic's message blocks (§5).

### 2.3 Data model (`backend/growthpilot/models.py`, Alembic in `backend/migrations/`)
Migration head: `b3c1d2e4f5a6`.

| Area | Tables |
|---|---|
| Accounts | `users`, `workspaces` (one brand each), `memberships`, `user_sessions`, `invites`, `oauth_states`, `audit_logs`, `app_meta` (stamps demo or live) |
| Brand | `brands` (profile, claims policy, colours, `catalogue_source`, `profile_sources`), `personas`, `products` (facts with provenance: `source_url`, `retrieved_at`, `image_kind`, `data_quality`, `is_active`), `assets` (files with `source`: upload, catalogue, rendered, ai_background) |
| Research | `research_findings` (each tagged with an evidence class), `competitors`, `competitor_observations` |
| Strategy | `campaigns`, `hypotheses`, `experiments`, `recommendations` |
| Content | `content_items` (versioned; `creative_brief` JSON; `approved_version` and `approved_hash`), `content_revisions`, `publish_attempts`, `metric_snapshots`, `reports` |
| Agent | `agent_runs`, `agent_steps`, `approval_requests`, `usage_records`, `cache_entries` |
| Channels | `channel_connections` (OAuth tokens encrypted with `ENCRYPTION_KEY`) |

**Don't commit databases.** To move data to production, write the SQLite-to-Postgres export in §9.4. Don't copy the
files by hand.

---

## 3. Target pipeline (end to end)

Each stage lists its input, its output (and where that's stored) and what's left to build. Stages 1–3 run once per
company, 4–11 per campaign, and 12 continuously.

```
[1 Onboard: link or CSV] → [2 Brand Brain] → [3 Catalogue + photos]
        ↓
[4 Goal] → [5 Research: Brave + site + competitors] → [6 Strategy: Groq] → [7 Calendar + mix]
        ↓
[8 Creative brief + caption + image prompt] → [9 Canva design (Pro)] → [10 Checks] → [11 Human approval]
        ↓
[12 Publish: Instagram / Facebook] → [13 Metrics] → [14 Learn → next campaign]
```

| # | Stage | Input → output (storage) | Code today | Left to build |
|---|---|---|---|---|
| 1 | Onboard any company | Website URL or CSV → draft profile and products for review | `POST /onboarding/scan-website`, `POST /onboarding/import-products`, `brand/page.tsx` CSV parser | Server-side CSV upload and validation; Shopify and WooCommerce readers; a "scan more pages" job for big catalogues; a re-scan schedule (§8) |
| 2 | Brand Brain | Draft → `brands` (voice, audience, claims policy, colours, pillars, platforms) | `PUT /brand` | Per-brand culture and compliance settings in place of the Poojaloka and India defaults (§8) |
| 3 | Catalogue + photos | Products and image URLs → `products` and `assets` (catalogue) | `catalogue/`, photo download | Object storage; freshness re-checks for any brand; trust rules for CSV images |
| 4 | Goal | Owner's goal text → `agent_runs` | `POST /runs`, `agent/intent.py` | Nothing |
| 5 | Research | Brave web search, the brand site, public competitor pages → `research_findings` and `competitor_observations` | `search_web`, `analyse_trends`, `collect_competitor_references` (cached, capped) | Nothing core; tune queries per industry and region |
| 6 | Strategy | Findings → `campaigns`, `hypotheses` (ranked), cost estimate | `create_campaign_plan`, `rank_campaign_ideas`, `estimate_campaign_cost` | Groq provider (§5) |
| 7 | Calendar + mix | Plan → `content_items` slots and an A/B `experiments` row | `prepare_schedule` | Nothing |
| 8 | Brief, caption, image prompt | Slot + facts → `content_items.creative_brief`, caption, hashtags | `create_content_brief`, `generate_caption` | An image-generation prompt field and generator (§4.4); make brief wording brand-neutral (§8) |
| 9 | Design in Canva Pro | Brief → Canva design → exported PNG/JPG → `assets` (source `canva`) linked to the post | — | The whole Canva integration (§4) |
| 10 | Checks | Post + image → `content_items.validation` | `verify_product_facts`, `validate_creative`, `services/validation.py` | Checks on Canva exports: the size, and that the required text is present (§4.5) |
| 11 | Approval | Exact version + image hash → approved | `request_human_approval`, `/approvals` UI | Email notifications (optional) |
| 12 | Publish | Approved post → Instagram/Facebook → `publish_attempts` | `adapters/instagram.py`, `adapters/facebook.py`, worker | Real Meta app and first verified post (§6) |
| 13 | Metrics | Platform insights → `metric_snapshots` | `retrieve_available_analytics`, worker collection | Verify with real accounts |
| 14 | Learn | Metrics → `experiments` results, `recommendations`, `reports` | analyst tools | Nothing core |

**Rules that must hold at every stage** (enforced in code today; keep them):
- **Approval:** nothing publishes without a person approving that exact version. Live publishing stays off until the
  owner enables it.
- **Facts:**
  - Claims (prices, offers, stock, materials, origin, health, purity) come only from verified product data.
  - Never invent engagement numbers.
  - Competitor material is used only as general patterns: never copied, never named.
- **Images:**
  - Stock photos are never shown as a product.
  - AI never generates a product's look; product imagery is the company's real photos only.
- **Secrets:** never logged, never in the frontend, never committed.

---

## 4. Canva Pro integration (design)

### 4.1 What Canva's API allows on Pro: check this first
- **Autofill (filling text and images into a brand template by API) needs a Canva Enterprise organisation.** Canva
  Pro can't use it. Sources: [Autofill guide](https://canva.dev/docs/connect/autofill-guide),
  [Autofill API reference](https://www.canva.dev/docs/connect/api-reference/autofills).
- **The Connect API covers** uploading assets, creating designs, and exporting finished designs back to your system
  ([Connect overview](https://www.canva.dev/docs/connect/)).
- **Confirm in the API reference before building:** the OAuth flow and scopes, the integration type (a private team
  integration versus a public one that needs Canva's review), rate limits, and the export formats.
- **Preview APIs** aren't meant for production and won't pass review in public integrations.

So with **Canva Pro**, the flow is **semi-automatic**: the agent prepares everything, and a person finishes the design
in Canva's editor. With **Enterprise**, it can become fully automatic through autofill (§4.6). Tell the owner which
one you're building.

### 4.2 Pro flow
1. **Connect Canva** once per workspace through OAuth. Store the tokens encrypted in `channel_connections` with
   `platform="canva"`; reuse `oauth_states` and the token encryption Meta already uses.
2. **For each post with a brief:**
   - Upload the brief's `image_refs` (real product photos or linked uploads) as Canva assets.
   - Create a design at the platform size: 1080×1350 for an Instagram post; sizes are in `platforms.py`.
   - Put the photo in only when `image_policy` isn't `text_only`.
   - Store the design id and edit URL on the post.
3. **The person opens the edit URL** from the post page. GrowthPilot shows the brief beside it:
   - the `required_text` to type in exactly
   - the layout and colours
   - the `canva_query` as the design instructions
   - the image prompt (§4.4) to use in Canva's AI image tools, if any
4. **Export:** when they click "Done" (or use Canva's return navigation, if available), GrowthPilot starts an export
   job, polls it, downloads the PNG/JPG and saves it as an `assets` row (`source="canva"`, `meta` holding the design
   id, export id and brief version). The worker can run the polling.
5. **Attach and check:** the export is linked as `content_items.asset_id` through `services/content.update()`. That
   bumps the version and clears approval. Then run validation (§4.5) and send the post for approval as usual.

### 4.3 API contract to implement
- **`POST /api/content/{cid}/canva-poster`:** creates or reuses the Canva design for the post.
  - Returns `{design_id, edit_url, status: "awaiting_edit"}`.
  - Refuses if the post has no `creative_brief`, or the brief has `needs_human_review` unresolved.
- **`POST /api/content/{cid}/canva-poster/export`:** starts the export. Returns `{job_id, status}`.
- **`GET /api/content/{cid}/canva-poster`:** returns the status: `none`, `awaiting_edit`, `exporting`, `attached` or
  `failed`, plus the asset id.
- **`POST /api/integrations/canva/start` and `GET /api/integrations/canva/callback`:** the OAuth flow. Mirror the
  Instagram routes in `api/routes/integrations.py`.
- **Agent tool `create_canva_design`** (Creative role, local write and external write): runs the first route for
  every briefed post in a run, then pauses with "designs ready to edit in Canva", like the approval pause.
- **Storage:**
  - Design id, edit URL, export status and the brief version used: add a `canva` JSON column on `content_items`, or
    a small `canva_designs` table.
  - One migration, chained after `b3c1d2e4f5a6`.

### 4.4 Image prompts (the agent's job)
- Add `image_prompt` to the brief:
  - `subject`
  - `style`
  - `composition`
  - `negative` (always: no text, no logos, no deities, no people's faces unless the brand allows them, no product
    lookalikes)
  - `aspect`
- **Generate it only for backgrounds or scenes. Never for the product itself.** When the post shows a product, the
  image must be the real photo.
- **Where the image gets made:**
  - Canva's own AI image tools inside the editor (a person pastes the prompt in).
  - Or `IMAGE_GENERATION_PROVIDER=gemini`, which already exists for AI backgrounds: about $0.034 an image on the
    paid tier, and not available on the free tier.
- Record every generated image as an `assets` row with `source="ai_background"` and its prompt in `meta`.

### 4.5 Checks on a Canva export
Reuse `services/validation.py` and `creative_ok`, plus:
- the export size matches the platform format
- the file is a JPEG or PNG under 8 MB (Instagram's limit)
- the brief's `required_text` is present (add an OCR step, such as Tesseract, or ask the person to confirm on
  approval)
- no prices or offers are visible unless they're claims allowed by the brief

### 4.6 Enterprise upgrade (later, optional)
Build one brand template per layout in Canva's Data autofill app. Then send `required_text`, the image refs and the
colours through the autofill job API, poll it, and export. The rest of the pipeline stays the same.

---

## 5. Groq as the main AI model

**Limits:**
- Model: `openai/gpt-oss-120b` through Groq's OpenAI-compatible API (`https://api.groq.com/openai/v1`, Bearer key).
- Free-tier limits reported by third-party pages (check your organisation's limits page in the Groq console): 30
  requests a minute, 1,000 a day, **8,000 tokens a minute** and 200,000 tokens a day.
- Limits apply per organisation, not per key.
- The Developer tier is reported at about 250,000 tokens a minute.

**Build `llm/groq_llm.py`** implementing the `LLM` protocol (`structured` and `tool_turn`):
- **Tools:** `{"type": "function", "function": {name, description, parameters}}`. Assistant tool calls carry
  `arguments` as a JSON string, and results come back as `role: "tool"` messages with `tool_call_id`. Translate
  to and from the Anthropic-style message blocks the planner stores, as `gemini_llm._steps` does.
- **Structured output:** `response_format: {type: "json_schema", json_schema: {..., strict: true}}`. Strict mode
  needs every property in `required` and `additionalProperties: false`, so add a schema adapter like Gemini's
  `inline_schema`.
- **Errors:** 401/403 means a bad key (not retryable); 429 means retry using the `retry-after` header (stop
  immediately when the daily limit is used up); 5xx is retryable.
- **Usage records:** call `usage.preflight` and `usage.record`. Add the Groq prices to `usage.TOKEN_PRICES`; record
  $0 on the free tier but keep counting tokens.

**Config (`config.py`):**
- add `groq_api_key` and `groq_model`
- accept `LLM_PROVIDER=groq`
- update `active_llm_provider` and `active_llm_model`
- add a "Test connection" check: the models list endpoint, which is free
- add tests like `tests/test_providers.py`

**Fitting 8,000 tokens a minute:**
- **The problem:** the planner sends all 26 tool definitions (about 5,000 tokens) every turn, which doesn't fit the
  free tier.
- **Compact tools:** send short descriptions and only the tools relevant to the current phase, and trim old tool
  results in the history.
- **Or a rules-led plan:** run the fixed step plan from `planner_demo.py` in live mode, with Groq only writing text
  through `structured()`. This uses about ten times fewer tokens and works on the free tier.
- **Or** pay for the Developer tier.
- Measure tokens per run before choosing, and record it in `docs/API_INTEGRATIONS.md`.

---

## 6. Instagram and Facebook (Meta)

The adapters exist (`adapters/instagram.py` uses "Instagram API with Instagram Login"; `adapters/facebook.py` uses
Facebook Login for Business with Pages). To make them work:

1. **Owner setup:** a professional Instagram account (Business or Creator) and a Facebook Page.
2. **Meta app:** create one at developers.facebook.com and add both products.
   - Instagram scopes: `instagram_business_basic`, `instagram_business_content_publish`,
     `instagram_business_manage_insights`.
   - Page scopes: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
   - Test with tester roles first.
3. **Config bug to fix:** Instagram Login issues its own app id and secret. Today both adapters read
   `META_APP_ID` / `META_APP_SECRET`, so add `INSTAGRAM_APP_ID` / `INSTAGRAM_APP_SECRET`.
4. **Callbacks:** a public HTTPS `BASE_URL` (the deployment, §9). Register `{BASE_URL}/api/integrations/instagram/callback`
   and `/facebook/callback`. Meta must be able to fetch images from `/api/public/assets/{token}.{ext}` (already
   built).
5. **App review:** to post for companies other than your testers, go through Meta's App Review (with a screencast)
   and Business Verification. Plan weeks, not days.
6. **Limits:** 100 API-published Instagram posts per 24 hours per account, JPEG only for Instagram.
7. **Tokens:**
   - Long-lived tokens expire after about 60 days, so add a worker job that refreshes them before expiry and marks
     the connection `needs_reauth` on failure.
   - `ChannelConnection.token_expires_at` already exists.
8. **First real post:** with the owner's written approval only, to their own account. Then verify `publish_verified`
   and the metrics collection.

---

## 7. Brave Search
- Already integrated in `research/search.py`: requests run in parallel, results are cached for 24 h in
  `cache_entries`, and there are caps per run and per day.
- Rotate the key, then just set `BRAVE_SEARCH_API_KEY`.
- Optional: add per-workspace search limits to settings (the defaults are on `workspaces`).

---

## 8. Making it work for any company (CSV or link)

These gaps come from the Poojaloka focus and must be closed:

- **Brand-neutral copy:**
  - `agent/briefs.py` (`copy_options`, `cta_for`) and parts of `agent/generation.py` and the demo generator use
    pooja and Poojaloka wording, plus a `poojaloka.com` link.
  - Build headlines, taglines and CTAs from the brand's own fields (name, pillars, categories, website, CTAs), with
    the model filling the templates and the existing validation checking them.
  - The brand name in `required_text` already comes from `brand.name`.
- **Configurable culture and compliance rules:**
  - The deity, mantra and Sanskrit rules, and the Indian festival calendar (`services/festival_dates.py`,
    `services/seasonal.py`), are right for Poojaloka but not universal.
  - Add a per-brand `content_policy` (region, religious-content rules, the festival calendars to use, banned topics),
    defaulting from the brand's location and industry. Keep India and Poojaloka as one preset.
  - Festival dates stay sourced: add a date only with its source, never estimated.
- **Validation vocabulary:** `services/validation.py`'s `MATERIALS` and certification lists are furniture- and
  pooja-oriented; make them extendable per brand or industry.
- **CSV import:**
  - **Endpoint:** add `POST /api/onboarding/import-csv` (multipart upload). It should accept a downloadable template,
    UTF-8 files with a BOM, and up to 5,000 rows.
  - **Validation per row:** price as a decimal, currency as ISO, `https` URLs only.
  - **Response:** row-level errors.
  - **Behaviour:** upsert by SKU, with provenance `source_url = product_url` or `"csv:<filename>"` and `retrieved_at`
    set to the upload time.
  - **Photo trust:** CSV `image_url` photos count as the company's own photos only if they're on the company's
    domain or uploaded; otherwise mark them `unverified` so they need review.
- **Website scans beyond a few pages:**
  - Follow the sitemap or `sitemap.xml`, respect robots.txt, and add a request delay. Run it as a background job
    with progress shown.
  - Sites that render products with JavaScript need a headless browser, behind a flag.
- **Store connectors:**
  - Shopify: the public `/products.json`, paginated.
  - WooCommerce: the Store API, `/wp-json/wc/store/v1/products`.
  - Both are free, need no key, and are more reliable than scraping. Add them as `CatalogueSource` implementations
    detected by the scan.
- **Freshness:** re-check prices and stock before scheduling, for every connector, not only Poojaloka
  (`catalogue.refresh`).
- **Multi-company:**
  - Each company is a workspace (one brand). The signup flow should create the workspace, then run the onboarding
    scan.
  - Platform connections (Meta, Canva) are per workspace.
  - API keys (Groq, Brave, Gemini) are per deployment. Track usage per workspace with the existing budgets.

---

## 9. Deployment (fully hosted, no gaps)

### 9.1 Target
```
Users ──HTTPS──▶ web (Next.js, npm start) ──/api──▶ api (FastAPI, uvicorn, 2+ instances)
                                                     ├──▶ PostgreSQL (managed, daily backups)
                                                     ├──▶ object storage (S3 / Cloudflare R2) for images
                                                     ├──▶ Redis (rate limits across instances)
                                                     └── worker (python -m growthpilot worker, 1+ processes)
External: Groq, Brave, Canva Connect, Meta Graph, (optional) Gemini image, email (Resend/SES)
```
- **Hosting:** Render, Railway or Fly.io all fit, with three services plus Postgres and Redis. Choose one with the
  owner; the costs need their approval.
- **Domain:** a custom domain with TLS, used as `BASE_URL=https://app.<domain>`.

### 9.2 Code changes needed for production
1. **Object storage:**
   - Replace `services/assets.AssetStore` with an S3-compatible store.
   - Keep the bytes immutable after approval (the approval hash covers them).
   - Serve public images through signed or tokenised URLs; `/api/public/assets/{token}` is the current pattern.
2. **Rate limits across instances:** `api/deps.rate_limit` is in-process today. Back it with Redis when `REDIS_URL`
   is set.
3. **Email:**
   - invite emails
   - password reset (missing today; add a token table and a reset route)
   - approval and publish-failure notifications
4. **Startup:**
   - Migrations run on API start today. In production, run `python -m growthpilot migrate` as a release step and
     start with `run_migrations=False`.
   - Run the worker as its own process (`RUN_WORKER_IN_PROCESS=false`).
5. **Observability:**
   - JSON logs, with secrets already redacted by `security.redact`
   - error tracking (Sentry)
   - a health check on `/api/health` (it already checks the database)
   - an uptime monitor
6. **Docker:**
   - verify `backend/Dockerfile`, `frontend/Dockerfile` and `docker-compose.yml` for real
   - add a compose override for production
   - build and push images in CI
7. **CI/CD:** keep tests and lint on PRs; deploy `main` to staging automatically and to production on a tag.
8. **Security:**
   - `APP_ENV=production`
   - an HTTPS `BASE_URL` (cookies become Secure automatically)
   - a strong `SECRET_KEY` and `ENCRYPTION_KEY`, kept in the host's secret store
   - CORS stays closed (the web app proxies `/api`)
   - review `docs/SECURITY.md`

### 9.3 Settings you'll set (values come from the owner; never commit them)
| Group | Settings |
|---|---|
| Core | `APP_MODE=live`, `APP_ENV=production`, `DATABASE_URL`, `SECRET_KEY`, `ENCRYPTION_KEY`, `BASE_URL`, `ASSET_DIR` (or the S3 settings), `REDIS_URL`, `RUN_WORKER_IN_PROCESS=false`, `WORKER_INTERVAL_SECONDS` |
| AI | `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL` (new), plus optional `GEMINI_API_KEY` / `IMAGE_GENERATION_PROVIDER` for images |
| Research | `SEARCH_PROVIDER=brave`, `BRAVE_SEARCH_API_KEY`, `SEARCH_CACHE_HOURS` |
| Canva (new) | `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, `CANVA_REDIRECT_URI` |
| Meta | `META_APP_ID`, `META_APP_SECRET`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` (new), `INSTAGRAM_API_VERSION`, `FACEBOOK_API_VERSION`, redirect URIs |
| Safety | `LIVE_PUBLISHING_ENABLED=false` until the owner approves the first real post |
| Email (new) | Provider key and from-address |

The `.env.example` file lists every current setting with comments. Add the new ones there too.

### 9.4 Moving existing data
- **Write `python -m growthpilot export-data` / `import-data`.** It copies every table from SQLite to Postgres in
  dependency order through SQLAlchemy, and copies the asset files to object storage, keeping each file's `sha256`
  so approvals stay valid.
- **Run it once for the owner's live workspace (SNITCH).** The demo database never moves to production.
- **Encrypted tokens** only work with the same `ENCRYPTION_KEY`; otherwise people reconnect their accounts.

---

## 10. Work plan and acceptance criteria

Merge PR #7 first, then get the teammate's Canva branch pushed. Each milestone ends with tests passing and a short
note in `TASKS.md`.

| # | Milestone | Done when |
|---|---|---|
| M1 | Groq provider (§5) | `LLM_PROVIDER=groq` starts the app. A full live campaign run completes on Groq within the tier's limits (rules-led plan or compact tools). Tokens per run are recorded. Tests cover tool calls, structured output and 429s. |
| M2 | Any-company onboarding (§8) | A non-Indian test company (e.g. a Shopify fashion store) and a CSV-only company each onboard with no Poojaloka wording anywhere. A culture and compliance setting exists. Server-side CSV import has row errors. The Shopify and WooCommerce readers work. |
| M3 | Image prompts (§4.4) | Briefs carry `image_prompt` with a negative prompt. No product imagery is ever generated. Optional generation is recorded as assets with the prompt. |
| M4 | Canva Pro (§4) | OAuth connect per workspace. `canva-poster` creates the design with the real photo at the right size. The person edits, then the export is attached as a new version and approval is cleared. Validation runs. The agent tool pauses runs for editing. Every Canva call is mocked in tests. |
| M5 | Meta for real (§6) | Separate Instagram app id. Token refresh job. One owner-approved real post on each platform, verified, with metrics collected. |
| M6 | Production (§9) | Hosted at an HTTPS domain on Postgres, object storage, Redis and a separate worker. Email invites and password reset. Sentry and uptime monitoring. Backups tested by restoring once. CI deploys staging. Data migrated. |
| M7 | End-to-end acceptance | For a brand-new company given only a link (and separately only a CSV): onboard, run "plan a week of posts", get briefs, captions and image prompts, Canva designs edited and exported, checks pass, a person approves, posts are scheduled, the publish is verified, metrics come back and a recommendation is made. No manual database work and no secrets in logs. |

## 11. Decisions the owner needs to make (ask early)
1. **Canva Pro (semi-automatic, a person finishes each design) or Enterprise (fully automatic autofill)?**
2. **Groq tier:** free with the rules-led plan, or the Developer tier with full model planning?
3. **Hosting provider and monthly budget,** and the domain name.
4. **Image generation:** Canva's in-editor AI only, or also an API such as Gemini image (paid)?
5. **Who completes Meta App Review and Business Verification,** and with which Facebook account?

## 12. Reference docs in this repo
- `docs/ARCHITECTURE.md`: system design and tool tags
- `docs/API_INTEGRATIONS.md`: provider details and prices
- `docs/DEPLOYMENT.md`: the current deployment notes; replace them with §9 once it's built
- `docs/SECURITY.md`: security rules
- `docs/KNOWN_LIMITATIONS.md`: current gaps
- `docs/creative-briefs/README.md`: the brief contract
- `docs/DEMO_SCRIPT.md`: a walkthrough of the demo
