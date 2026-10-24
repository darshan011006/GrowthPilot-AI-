# Demo script — Poojaloka (about 8 minutes)

Setup: `make setup && make demo && make dev`, open http://localhost:3000 and sign in with `data/demo-login.txt`.
To start clean: **Settings → Demo data reset → Poojaloka → type RESET**.

What's real: Poojaloka's catalogue (a dated snapshot from its public storefront API), its festival guides,
articles, colours and fonts. What's labelled: two fictional competitors, fixture trend notes, synthetic metrics and
simulated publishing (orange banner, "Synthetic" / "Fixture" / "simulated" badges). No external or paid calls.

## 1. The problem (30 s)
"Small retailers post a lot and learn little, and generic AI tools invent prices, offers and product details.
GrowthPilot is a marketing team in one app: it researches, plans, creates real images, checks every fact, asks
before it publishes on any platform, and learns from results."

## 2. The brand, from its own data (60 s)
**Brand Brain**: the colour dots and "Where this profile came from" (homepage, stylesheet; voice/audience marked as
suggestions). **Catalogue**: 40 real products with price and struck-through MRP, stock, a **freshness** badge and a
**source ↗** link to poojaloka.com. Point at the flags: "₹1 price" and "negative stock" (won't be promoted), "chair"
(a test listing), and **stock image only** — "the store shows generic stock photos for 2,876 of 2,877 products, so
GrowthPilot never uses them as the product." **Festivals & articles**: the store's own Deepavali guide with the
items needed.

## 3. One goal, seven-platform plan (2 min)
**Agent Command Centre** → first example:
> Create a seven-day Deepavali campaign for Poojaloka's diyas, brass items and pooja essentials across Instagram,
> Facebook, Pinterest and Threads, aimed at families in Bengaluru.

On the run page:
* **Agent team** strip: Research, Strategy, Creative, Verification, Distribution, Analyst — click one to filter.
* **Live activity**: plain-language steps with role chips and "Orchestrator → … Agent" delegation lines.
* **Searching the web → Blocked → Re-plan**: no live search in demo, so Research uses the store's festival pages,
  the seasonal calendar and labelled fixtures. *(Agentic behaviour: tool choice depends on what's available.)*
* **Checking product facts**: decision note that products have no real photo → typographic product cards.
* **Writing the campaign strategy**: objective metric *saves per reach*, channel mix with reasons, competing
  hypotheses; **Ranking**: weighted criteria incl. cost, risk and feasibility (a heuristic, not a probability).
* **Rendering poster images → Re-plan**: the "Festival offers" post said "Festive offers…", which isn't an approved
  claim (on the caption *and* the poster). Verification sends it back; Creative rewrites it as a factual product
  post from catalogue data and re-renders; Verification passes it. *(Agentic behaviour: recovery after failed
  verification.)*
* **Adapting posts for each platform**: 21 variants (Facebook, Pinterest, Threads) with platform-sized images.
* Open **Details** on any step: specialist, side effects, evidence ids, tool input and result, cost ($0 in demo).
* **Outputs**: thumbnails of the rendered images.

Optional: run the second example (*all seven platforms*) to show the YouTube decision: "video only → brief, not sent
for publishing", and X captions kept under 280 characters.

## 4. Approve exact versions (60 s)
**Approval Inbox**: one card per post with a tab per platform. Each tab shows the realistic platform preview, the
verification results, image checks and the evidence. "Each platform version is approved separately and the approval
covers these exact image files." Approve one tab, then **Approve all passing versions** for the rest (with the
warnings box ticked — e.g. "price from a snapshot N hours old").

The run resumes automatically and schedules each approved version on its platform (**Calendar** shows platform chips;
drag a draft to another day to re-plan it).

## 5. Creative Studio and publishing (60 s)
**Creative Studio** (gallery) → open a scheduled Instagram post:
* Platform tabs for its Facebook / Pinterest / Threads versions.
* **Creative** card: check badges (contrast, safe margin, text fit, dimensions), PNG/JPG download, "No real product
  photo available: typographic product card used".
* **Version history → Compare**: highlighted text changes and before/after images.
* **Publish now** → demo adapter → "verified by provider", **simulated** badge. The Facebook tab is still
  "Scheduled": publication is tracked per platform.
* **Asset Library**: every image with provenance, SHA-256, the text layers and their contrast ratios.

## 6. Learn and adapt (90 s)
**Agent Command Centre** → *Evaluate last month's results and recommend what to change next.*
* **Experiments**: "Festival-guide carousels vs product showcases (synthetic history)" — evaluated **on Instagram
  only**, primary metric saves per reach, lift, p-value and a **confidence** level; "association, not proof";
  "SYNTHETIC demo metrics".
* **Recommendations** with a concrete **Proposed change** (e.g. move "Festival guide" to the top of the content
  pillars) → **Approve & apply change** (owner, audited). Nothing changes without approval.
* **Reports**: channel mix, per-platform content table, experiments, cost.

## 7. Trust, cost and the path to production (30 s)
**Integrations**: Gemini, Claude, Brave and AI backgrounds with real **Test connection** buttons (live mode); seven
platform cards with honest status ("live adapter built, not yet verified" for Instagram/Facebook; "not built yet,
simulated only" for the rest) and what each needs from you. **Usage & Budgets**: per-run and monthly budgets, the
single-step approval threshold, search caps, the price list used for estimates.

"Add a Gemini key and the same orchestrator plans with an LLM; add a Brave key for live research; sync the live
catalogue; connect a Meta app to publish to Instagram and a Facebook Page. The guardrails don't change."

## Fallback
* Run stuck? **Pause** / **Cancel**, or **Retry from where it stopped**. **Settings → Reset demo data** restarts.
* API restarted mid-run? The worker recovers the run and continues without redoing completed steps.
