# Deployment

GrowthPilot is two processes plus a database: the **FastAPI API** (which can also run the background worker) and
the **Next.js web app**, which proxies `/api/*` to the API so the browser only ever talks to one origin.

```
Browser ──HTTPS──▶ reverse proxy (TLS) ──▶ Next.js :3000 ──/api/*──▶ FastAPI :8000 ──▶ PostgreSQL
                                                                      │  └──▶ asset volume (images)
                                                         worker ◀─────┘  (in-process or separate)
```

Status: the local setup (SQLite, in-process worker) is what's tested. PostgreSQL and the Docker files are written
but haven't been run here — verify them in your environment first.

## Components

| Component | Local (free) | Production | Notes |
|---|---|---|---|
| API | `make dev` (uvicorn) | `python -m growthpilot serve --host 0.0.0.0` behind a proxy, or `backend/Dockerfile` | Runs Alembic migrations on start |
| Web app | `next dev` | `npm run build && npm start`, or `frontend/Dockerfile`; set `BACKEND_URL` to the API's internal URL | No secrets in the frontend |
| Worker / scheduler | inside the API process | `RUN_WORKER_IN_PROCESS=false` on the API, plus one or more `python -m growthpilot worker` processes | Database-backed queue with atomic claims; safe to run several. Wakes every `WORKER_INTERVAL_SECONDS` to run agent runs, publish due posts and collect metrics |
| Database | SQLite in `data/` | PostgreSQL (`DATABASE_URL=postgresql+psycopg://…`) | One database per mode; stamped and refused if mismatched |
| Media storage | `data/assets-<mode>/` | a persistent volume mounted at `ASSET_DIR` | Approval hashes cover the image bytes, so files must not change after approval. For object storage, replace `AssetStore` in `services/assets.py` |
| TLS / public URL | not needed for demo | a domain or tunnel; `BASE_URL=https://…` | Needed for Secure cookies, OAuth callbacks and Meta fetching images |
| Redis | not needed | not needed | Rate limits are per process; use a gateway if you run several API instances |

## Step by step (single VM)

1. Provision PostgreSQL and create a database.
2. `cp .env.example .env` (or `make env`), then set at least: `APP_MODE=live`, `APP_ENV=production`,
   `DATABASE_URL`, `BASE_URL` (public HTTPS), `ASSET_DIR`, `GEMINI_API_KEY`, `BRAVE_SEARCH_API_KEY`.
   `SECRET_KEY` and `ENCRYPTION_KEY` must be set (`make env` generates them). Keep `ENCRYPTION_KEY` safe: it decrypts
   stored OAuth tokens.
3. Install: `make setup` (or build the two Dockerfiles). Start the API, the worker (if separate) and the web app
   under a process manager (systemd, supervisord) or `docker compose up`.
4. Put a reverse proxy (Caddy, nginx) in front of the web app with TLS. Only the web app needs to be public.
5. Open the app, register the first owner account, then **Brand Brain → Catalogue → Sync now** and **Integrations
   → Test connection** for each provider.
6. Set **Usage & Budgets** before the first run.

## OAuth callbacks

Register exactly these with Meta (they're also shown on the Integrations page in live mode):

* Instagram: `{BASE_URL}/api/integrations/instagram/callback`
* Facebook Pages: `{BASE_URL}/api/integrations/facebook/callback`

`BASE_URL` must be the public HTTPS origin of the web app. For a demo, a tunnel works:
`cloudflared tunnel --url http://localhost:3000` (use the printed URL as `BASE_URL` and in the Meta app).

## Public image URLs

Meta fetches post images from `{BASE_URL}/api/public/assets/<unguessable-token>.jpg`. These URLs serve only JPEG/PNG
files and are unauthenticated by design. Remove a connection or delete an asset to stop serving it.

## Backups

PostgreSQL: `pg_dump`. Assets: back up `ASSET_DIR`. Keep `ENCRYPTION_KEY` with the backups (without it, users would
need to reconnect integrations).

## What's free and what costs money

| Item | Cost | Notes |
|---|---|---|
| Demo mode | free | No external or paid calls |
| Poster rendering | free | Local Pillow renderer |
| Poojaloka catalogue sync | free | Public storefront API |
| Gemini API | per token | Some models have a free tier with lower limits; Flash prices rise on 2027-01-01 |
| Claude API (optional) | per token | Separate from Claude subscriptions |
| Brave Search | $5 / 1,000 requests | Monthly credit applied first; cached and capped |
| Gemini image backgrounds (optional) | ≈ $0.03 per image | Off by default |
| Instagram / Facebook Graph APIs | free | Need App Review for non-tester accounts |
| X API | paid plans | Live adapter not built |
| Hosting | your provider | Any small VM can run the API, worker and web app |

GrowthPilot records an estimated cost for each paid call and stops for owner approval before crossing the per-run,
per-campaign, monthly or single-step limits. Estimates use the price table in `backend/growthpilot/usage.py`
(checked 2026-10-24); your provider's bill is authoritative.

## Health checks

* `GET /api/health` (API liveness and database).
* Settings → System health in the app (mode, database, worker, live-publishing switch, configuration gaps).
* Logs never include secrets (`redact()` on errors); look for `worker tick` lines to confirm the scheduler is running.
