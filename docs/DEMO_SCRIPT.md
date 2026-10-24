# Demo script (about 7 minutes)

Setup: `make setup && make demo && make dev`, open http://localhost:3000 and sign in with `data/demo-login.txt`.
To start clean: **Settings → Reset demo data** (type RESET).

Everything shown runs for real on the backend. The brand is fictional, and research, competitor data and metrics
are labelled fixtures or synthetic, as the orange banner and the "Synthetic" / "Mock / fixture" badges show.

## 1. The problem (30 s)
"Furniture brands post a lot of pretty pictures and learn very little. Generic AI tools make it worse: they invent
prices, materials and discounts. GrowthPilot is a marketing agent that works from evidence, checks every claim, asks
before it publishes, and learns from results."

## 2. Brand Brain (45 s)
**Brand Brain → Products**: the Kabini sofa collection, with exact prices, dimensions, materials and verified
attributes (e.g. "warranty: 5 years on the frame"). **Claims & sources**: approved claims, restricted claims,
prohibited messaging. "The agent may only state these facts."

## 3. Give the agent a goal (90 s)
**Agent Command Centre** → click the first example:
> Create a seven-day Instagram campaign for our new Kabini sofa collection aimed at urban homeowners in Bengaluru
> ahead of Diwali.

On the run page, point out:
* **Plan** (right): 18 steps chosen for a campaign goal.
* **Step 5 `search_web` → Blocked** and **Re-plan**: live search isn't available in demo mode, so it switches to
  labelled trend fixtures and the built-in seasonal calendar. *(Agentic behaviour 1: tool choice depends on what's
  available.)*
* **`identify_content_gaps`**: "Compact living", "Materials" and "Styling" are backed by signals but barely covered
  by competitors (43% of competitor posts push discounts).
* **`rank_campaign_opportunities`**: the dimension-led carousel hypothesis wins, with a visible score breakdown that
  is labelled a heuristic, not a probability.
* **`validate_product_claims` → 1 fail → Re-plan → revise → re-validate → pass**: the festive post said "Festive
  offers…", but no offer is an approved claim, so the agent removed it. *(Agentic behaviour 2: plan revision after
  failed validation.)* Note: the demo generator's festive template intentionally uses offer wording, like a typical
  LLM draft, to exercise this path.
* **Approval** step: the run is now paused, waiting for a person.

Click **Show tool input/output** on any step to show the raw records.

## 4. Approve (60 s)
**Approval Inbox**: each card shows the exact final caption and image, target account, planned time (Asia/Kolkata),
campaign objective, the hypothesis being tested, the supporting evidence with sources, and every claim check.
Approve a couple. "Approval is bound to v4. If anyone edits it, it goes back to draft."
Optional: open a post in **Creative Studio**, change a word, save, and show the approval is cleared and the version
history updated.

Approve the rest. The agent run resumes automatically and schedules them (**Calendar** shows the week).

## 5. Publish (30 s)
Open a scheduled post → **Publish now**. It goes through the demo Instagram adapter (container → publish → verify),
shows "verified by provider" and a **simulated** badge, and records the attempt. "In live mode this is the real
Instagram API, gated by `LIVE_PUBLISHING_ENABLED`, the owner's publish authorisation and a confirmation."

## 6. Learn and adapt (90 s)
**Agent Command Centre** → example 4: *Evaluate last month's results and recommend what to change next week.*
* `collect_post_analytics` → `compare_content_performance` (by type and pillar, with sample sizes and caveats) →
  `evaluate_experiment` → `revise_marketing_strategy` → `generate_campaign_report`.
* **Experiments**: "Styling carousels vs single product shots (synthetic history)": variant B was associated with a
  higher engagement rate. Show n per variant, the permutation p-value, and the explicit statements "association,
  not proof" and "SYNTHETIC demo metrics". The new campaign's experiment is inconclusive and still collecting.
* **Recommendations** and the planned next experiment. *(Agentic behaviour 3: strategy adapts to observed
  performance.)*
* **Reports**: the full campaign report, with a demo-data notice.

## 7. Trust and the path to production (30 s)
**Integrations**: each service shows its true state (demo adapter, not configured, configured, connected and
verified, expired), plus Instagram's capabilities and the exact redirect URI. **Settings**: agent budgets
(steps/tokens/timeout), roles, the audit log of every approval and publish, and system health.

"Swap in an Anthropic key and Claude plans with the same 26 tools. Add a Meta app and it publishes to a
professional Instagram account. The guardrails don't change."

## Fallback if something goes wrong
* Agent stuck? **Cancel run**, then **Settings → Reset demo data**.
* API down? `make dev` again; the run picks up from the database.
