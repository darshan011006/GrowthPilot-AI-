# API integrations

Status key: **Verified** = exercised against the real service. **Implemented** = built from current official
docs and tested against a mocked API, not yet run with real credentials. **Demo** = mock adapter, labelled.

| Integration | Mode | Status | Needs from you |
|---|---|---|---|
| Anthropic Claude (LLM) | live | Implemented | API key |
| Brave Search (web research) | live | Implemented | API key |
| Public page fetch (`inspect_website`) | live | Implemented, tested with mocked pages | nothing; list permitted domains in Brand Brain |
| Instagram API with Instagram Login | live | Implemented, tested against a mocked Meta API | Meta app, professional IG account, public HTTPS URL |
| Signed webhook (Zapier / Make / n8n) | live | Implemented, tested against a mock receiver | a webhook URL |
| Demo Instagram adapter | demo | Demo | nothing |
| Image generation | — | Not implemented | — (upload real photos instead) |
| Pinterest / TikTok / YouTube | — | Not implemented | — |

Check any key from **Integrations → Test** (owner only). Results never show the key.

---

## Anthropic Claude

Used by the live agent planner (tool use) and live content generation (structured outputs).

1. Create a key at https://console.anthropic.com → API keys. API usage is billed per token, separately from Claude.ai or Claude Code subscriptions.
2. In `.env`: `LLM_PROVIDER=anthropic`, `LLM_API_KEY=…`, optionally `LLM_MODEL` (default `claude-opus-5-5`) and
   `LLM_EFFORT` (default `medium`).
3. Restart, then **Integrations → LLM → Test** (a free model-lookup call).

Implementation (`backend/growthpilot/llm/anthropic_llm.py`): official `anthropic` Python SDK 2.x,
`beta.messages.parse` with Pydantic `output_format` for schema-validated outputs, `beta.messages.create` with typed
tools for the agent, `output_config.effort`, prompt caching, and `fallbacks="default"`
(`server-side-fallback-2026-07-01`) so a safety refusal is retried on Anthropic's recommended fallback model.
`refusal` and `max_tokens` stop reasons become clear errors. Per-run token use is tracked against the workspace
budget.

## Brave Search

Used by `search_web` and `collect_trend_signals` in live mode.

1. Get a key at https://brave.com/search/api/ (check current plans and quotas there).
2. `.env`: `SEARCH_PROVIDER=brave`, `SEARCH_API_KEY=…`.
3. **Integrations → Web research → Test** runs one search, which counts toward your quota.

Endpoint: `GET https://api.search.brave.com/res/v1/web/search` with header `X-Subscription-Token`, params `q`,
`count`, `country`, `freshness`. Each result becomes a `source_reported` finding with URL, title, snippet and
retrieval time. Snippets and titles are scanned for prompt-injection phrasing and flagged; they're never treated as
instructions. Without a key, the agent says research is unavailable and continues with the built-in seasonal
calendar.

## Public page fetch (`inspect_website`)

No key. Only https, only the brand's own site, competitor sites and the domains in **Brand Brain → Claims &
sources → Permitted research sources**. robots.txt is honoured. Private, loopback, link-local and metadata
addresses are blocked, and redirects are re-validated hop by hop. Responses are limited to 1 MB, and login walls or
paywalls (401/402/403) are reported, not bypassed. Page text is stored as data and wrapped as
`<untrusted_content>` before a model sees it.

## Instagram (Meta) — Instagram API with Instagram Login

Verified against Meta's docs on 2026-10-24
(https://developers.facebook.com/docs/instagram-platform/content-publishing,
…/instagram-api-with-instagram-login/business-login, …/reference/instagram-media/insights).

### What you need to do

1. **Instagram account:** switch the brand account to a **professional account (Business or Creator)** in the
   Instagram app (Settings → Account type and tools). Personal accounts can't publish via the API; GrowthPilot
   checks `account_type` and refuses them.
2. **Meta app:** at https://developers.facebook.com/apps create an app and add the **Instagram** product, choosing
   *API setup with Instagram login*.
3. **Redirect URI:** register exactly `{BASE_URL}/api/integrations/instagram/callback` (shown on the Integrations
   page). `BASE_URL` is the URL people open the app at, e.g. `https://growthpilot.example.com`.
4. **Credentials:** copy the Instagram App ID and App Secret into `.env` as `META_APP_ID` and `META_APP_SECRET`.
5. **Testing before App Review:** while the app is in development mode, only accounts with a role on the app can
   authorise it. Add the brand's Instagram account as a tester under App roles and accept the invite from that
   Instagram account. Using it with accounts that have no role on the app requires Meta App Review for the
   permissions below, and may require business verification. Check Meta's current requirements.
6. **Public HTTPS for images:** Meta downloads post images from a public URL when you publish. Set `BASE_URL` to
   a public HTTPS address. For a demo, a tunnel works, for example `cloudflared tunnel --url http://localhost:3000`
   or `ngrok http 3000`; use that URL as `BASE_URL` and as the redirect URI. Images are served from unguessable
   `/api/public/assets/<token>.jpg` URLs (JPEG/PNG uploads only).
7. **Photos:** upload real product photos as **JPEG** (Instagram publishing accepts JPEG only; feed aspect ratio
   4:5 to 1.91:1). Placeholders are blocked from live publishing.
8. **Turn on publishing deliberately:** `LIVE_PUBLISHING_ENABLED=true`. Even then, each post needs owner
   approval, a "publish this exact version" authorisation, and a confirmation when scheduling.

### Scopes requested
`instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights` (for
metrics). Without insights permission, analytics show "not available" rather than zeros.

### Flow implemented (`backend/growthpilot/adapters/instagram.py`)
1. `https://www.instagram.com/oauth/authorize` with `state` (random, stored hashed, single use, 10-minute expiry,
   bound to the user and workspace).
2. `POST https://api.instagram.com/oauth/access_token` → short-lived token →
   `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token` → 60-day token, Fernet-encrypted.
3. Verify the account (`/me`: username, account_type) before marking it **Connected & verified**.
4. Publish: check `content_publishing_limit` → `POST /{ig-id}/media` (image_url, caption, alt_text) →
   poll `status_code` until `FINISHED` (retry later if still `IN_PROGRESS`; fail on `ERROR`/`EXPIRED`) →
   `POST /{ig-id}/media_publish` → media id → verify via `GET /{media-id}?fields=permalink,timestamp`.
   Carousels: child containers (`is_carousel_item`) then a `CAROUSEL` container (2–10 images).
5. Token refresh in the last 7 days of validity (token at least 24h old). An expired or revoked token marks the
   connection **Expired — reconnect**.
6. Insights: `GET /{media-id}/insights?metric=reach,likes,comments,shares,saved,views`.

### Not supported yet
Reels and stories (they need video upload), Instagram via Facebook Login (needed for Business Discovery of
competitor accounts), and comment/DM management.

## Signed webhook

Hand approved posts to Zapier, Make, n8n or your own service, which then posts anywhere. **Integrations → Add
webhook** shows the signing secret once. Each request is a JSON `POST` with `X-GrowthPilot-Timestamp` and
`X-GrowthPilot-Signature: sha256=HMAC_SHA256(secret, "<timestamp>.<raw body>")`. https only, private targets
blocked (unless `ALLOW_INSECURE_WEBHOOKS=true` for local testing), and redirects aren't followed. Delivery is
recorded as **Delivered**; whether it was actually posted is up to the receiver, and the UI says so.

## Image generation

Not implemented. `generate_image_asset` uses a real product photo when the product has one, otherwise a clearly
marked SVG placeholder built from the image brief. The `IMAGE_GENERATION_*` variables are reserved for a future
provider adapter.

## Environment variables
See [`.env.example`](../.env.example) for the full list with comments.
