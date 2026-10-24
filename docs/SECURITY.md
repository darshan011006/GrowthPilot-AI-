# Security

## Principles
* Secrets stay on the server. The browser never receives API keys, OAuth tokens or signing secrets.
* Nothing is published to a real account without explicit human approval of that exact version.
* External content (web pages, search results, competitor posts) is untrusted data, never instructions.
* Demo and live data never mix.

## Controls

| Area | Control | Where |
|---|---|---|
| Passwords | Argon2 hashing; policy of 10+ chars, mixed case and a digit | `security.py` |
| Sessions | Random token in an HttpOnly, SameSite=Lax cookie (Secure when `BASE_URL` is https); stored as SHA-256; 12h expiry; logout and password change revoke sessions | `api/deps.py` |
| CSRF | Per-session token required in `X-CSRF-Token` on every mutating request; login/register require JSON + `X-Requested-With`, and no CORS is enabled | `api/deps.py` |
| Authorisation | Roles enforced server-side: owner (approve, authorise publishing, integrations, members), editor (create, run the agent), viewer (read). Every query is workspace-scoped (`Ctx.get`) | `api/` |
| Registration | First user creates the workspace; after that invite-only (hashed, single-use, 7-day tokens) | `routes/auth.py` |
| Rate limiting | Login (10 per 15 min per IP+email), registration, agent runs, uploads, regeneration, integration tests | `api/deps.py` |
| Secrets at rest | OAuth tokens and webhook secrets encrypted with Fernet (`ENCRYPTION_KEY`); never serialised | `security.py`, `serializers.py` |
| Secret redaction | Errors and logs pass through `redact()` (bearer tokens, `access_token`, `client_secret`, `sk-ant-…`); provider errors never echo API keys (tested for Gemini) | `security.py`, `llm/` |
| OAuth | Random `state`, stored hashed, single use, 10-minute expiry, bound to user and workspace; redirect URI fixed from config | `routes/integrations.py` |
| SSRF | https only for research; private/loopback/link-local/reserved/multicast addresses blocked after DNS resolution; per-hop redirect checks; domain allow-list; 1 MB cap; no credentials in URLs; non-standard ports blocked | `research/net.py` |
| Prompt injection | External text wrapped in `<untrusted_content>` with an explicit no-authority note; injection phrases flagged; tools enforce policy regardless of model output (publishing needs human approval in the database, not a model's say-so) | `research/web.py`, `agent/` |
| Tool permissions | Typed schemas (`extra="forbid"`); every tool declares its role and side effects; only `publish_approved_content` can post publicly and it refuses anything not approved, scheduled and unchanged; no shell, SQL or arbitrary HTTP tools | `agent/registry.py`, `agent/tools/` |
| Approval binding | Approval stores a SHA-256 over the exact text, platform, type and image bytes; recomputed at scheduling and publishing; DB CHECK constraint ties approved/scheduled/published status to the current version | `services/content.py`, `models.py` |
| Spending | Budget pre-checks before every paid call (run, campaign, monthly, single-step threshold); runs pause for owner approval; search caps and cache; estimates recorded per call | `usage.py`, `research/search.py` |
| Catalogue ingestion | Public read-only storefront endpoints only, identified User-Agent, SSRF-checked, paced; stock images never treated as product photos; snapshot in demo (no network) | `catalogue/` |
| Generated images | On-image text claim-checked; AI backgrounds forbid text, products, people and deities and are labelled on the image | `services/creative.py`, `creative/imagegen.py` |
| Publishing safety | `LIVE_PUBLISHING_ENABLED` (off by default, forced off in demo); owner approval bound to version; separate publish authorisation; confirmation on schedule; send-time re-checks; unique idempotency key per version; no automatic re-publish after a crash; 6-hour lateness cutoff | `services/content.py`, `services/publishing.py` |
| Uploads | 8 MB cap; type sniffed from bytes (JPEG/PNG only); random storage names; path traversal blocked; public URLs only for JPEG/PNG with unguessable tokens; SVG placeholders never public | `services/assets.py` |
| Output safety | React escaping; no `dangerouslySetInnerHTML`; reports rendered by a React Markdown subset; external links `rel="noopener noreferrer nofollow"` | `frontend/src` |
| Headers | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Cache-Control: no-store` on API, HSTS when https | `api/app.py`, `next.config.ts` |
| Audit | Logins, approvals, scheduling, publishing, connections, member changes, demo resets; no secrets in details | `audit.py`, Settings → Audit log |
| Demo/live separation | Separate databases, stamped with their mode; mismatch refused; live mode refuses demo DB names and placeholder secrets | `config.py`, `db.py` |
| Dependencies | `pip-audit` and `npm audit` clean on 2026-10-24; both run in CI | `.github/workflows/ci.yml` |

## Known gaps
* DNS rebinding: the SSRF check resolves the hostname, then the HTTP client resolves it again. Pinning the
  resolved IP would close this; it's acceptable for an owner-configured, allow-listed set of domains.
* Rate limits are in-process memory (a single API instance). Use Redis or a gateway for multiple instances.
* No MFA and no SSO. Sessions are 12 hours.
* Uploaded images aren't re-encoded (EXIF metadata is kept).

## Backups
SQLite: stop the app and copy `data/live.db` and the asset directory, or use `sqlite3 data/live.db ".backup x.db"`.
PostgreSQL: `pg_dump`. Keep `ENCRYPTION_KEY` with backups; without it, stored tokens can't be decrypted (users
would reconnect integrations).

## Reporting
Never publish test content to real accounts. Use the demo adapter, or the webhook adapter pointed at a receiver you
control.
