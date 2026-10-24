# Known limitations (as of 2026-10-24)

## Not verified against real services
These are implemented from current official docs and covered by tests with mocked APIs, but have **not** run
against the real service because no credentials were available:
* **Anthropic Claude**: the live planner (tool use) and live generator (structured outputs). The planner loop is
  tested with a scripted fake model. Prompt quality, effort tuning and token cost on real goals are unmeasured.
* **Brave Search**: request/response handling is tested with a mocked endpoint.
* **Instagram API with Instagram Login**: OAuth, token exchange and refresh, account verification, container →
  status → publish → verify, publishing limit and insights are tested against a mocked Meta API. Real-world
  behaviour (scopes granted in development mode, App Review, exact error codes, insight availability) needs a Meta
  app and a professional account. Blockers: see API_INTEGRATIONS.md.

## Infrastructure not exercised
* **PostgreSQL**: supported through SQLAlchemy with the `psycopg` driver installed, but the suite runs on SQLite
  because PostgreSQL isn't installed here.
* **Docker Compose / Dockerfiles**: written, never built (Docker isn't installed).
* **GitHub Actions**: runs tests, lint, type check, build and dependency audits on every push. Docker images are not built in CI.
* **Redis**: not used; the queue is database-backed. Rate limits are per process.

## Product limitations
* Instagram only for real publishing. Reels and stories can be planned and briefed but not published (video upload
  isn't implemented). Pinterest, TikTok and YouTube have no adapters; the webhook adapter can bridge to them.
* No image generation provider: real product photos, or labelled placeholders that are blocked from live publishing.
* Competitor research uses public websites only. Instagram data for other accounts (Business Discovery) needs the
  Facebook Login variant of the API, which isn't implemented. Private metrics are always "not available".
* Live search needs a Brave key; without one the agent uses only the built-in seasonal calendar, which has
  hand-entered festival dates that should be confirmed locally.
* Posting times (13:00 / 19:30 local) are a starting heuristic, not learned best times.
* One brand per workspace in the UI (the data model supports several).
* Invites are links to share manually; there is no email sending. No MFA or SSO.
* Manual metric entry is live-mode only; demo metrics are always synthetic.
* Experiment statistics are deliberately simple (difference in means, permutation test, p < 0.10 screening, and a
  3-post minimum per variant). With small samples most results are "inconclusive", which is intended.
* The demo generator is template-based. Its festive template uses offer wording on purpose to show the claim
  validator; real LLM drafts vary.
* The claim validator is rule-based: it catches prices, offers, warranties, stock and delivery promises,
  certifications, materials and dimensions, but can produce false positives (e.g. a non-product material mentioned
  as décor) and can't judge subjective claims.
* The dashboard is client-rendered behind a client-side session check, so Next.js instant-navigation validation is
  limited to explicit opt-ins (`validationLevel: manual-warning`).
* No baseline evaluation harness yet (agent vs one-shot LLM campaign). No superiority claims are made.

## Security gaps
See docs/SECURITY.md → Known gaps (DNS-rebinding window in the SSRF check, in-memory rate limits, no MFA).
