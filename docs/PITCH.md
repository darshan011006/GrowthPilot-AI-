# GrowthPilot AI — pitch

**One line:** An AI marketing department for furniture brands that works from evidence, checks every claim, asks
before it publishes, and learns from results.

## Problem
Furniture is a considered, high-ticket purchase. Small and mid-sized furniture brands post constantly on Instagram
but rarely learn what works. Generic AI content tools speed up posting but invent prices, materials, discounts and
warranties, which is a real legal and brand risk. They also have no memory of what worked last time.

## What GrowthPilot does
1. **Knows the brand**: catalogue facts, approved and forbidden claims, voice, personas.
2. **Researches with provenance**: trend signals, the seasonal calendar and public competitor content, each tagged
   as verified, source-reported, inference or hypothesis, with its source.
3. **Finds a gap and forms competing hypotheses**, ranked on transparent criteria.
4. **Creates and validates**: captions, carousels and briefs, checked against the catalogue and claims policy,
   revised automatically when a check fails.
5. **Asks first**: an approval inbox where a person approves the exact version. Edits require re-approval.
6. **Publishes safely** through a verified Instagram connection, with idempotent, verified publishing and a kill
   switch.
7. **Measures and adapts**: experiments evaluated with sample-size checks and honest uncertainty, then the next
   experiment.

## Why it's different
* **Agentic, observably.** A stateful Observe → Plan → Act → Evaluate → Re-plan loop over 26 typed tools, with
  every step, input, output, retry and budget visible. In the demo you can watch it re-plan when search is
  unavailable, revise a post that made an unapproved offer, and change strategy based on experiment results.
* **Evidence over vibes.** Claims are verified against product data. Findings carry provenance. Scores are labelled
  heuristics. Results say "association, not proof".
* **Human control by design.** Version-bound approval, separate publish authorisation, and a global live-publishing
  switch that is off by default.

## What's real today
Working backend, frontend, agent and demo end to end (63 automated tests plus a browser test). The Instagram,
Claude and Brave integrations are implemented to current docs and tested against mocks; they need credentials to
verify. See KNOWN_LIMITATIONS.md. We make no claims about uplift, adoption or benchmarks; none have been measured.

## Path to SaaS
Multi-workspace auth and roles already exist. Next: Facebook Login variant (competitor Business Discovery),
Pinterest, an image generation provider, reels, PostgreSQL and Redis deployment, and an evaluation harness against a
one-shot baseline.
