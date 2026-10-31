# Creative briefs (schema 1.0)

The existing `create_content_brief` tool writes one `CreativeBrief` per planned post and saves it on the
content item as `creative_brief` (returned by `GET /api/content/{id}`). Saving a brief creates a new content
version, and a changed brief clears any approval. Nothing here renders a design, calls Canva or publishes.

`brief-1.json` … `brief-5.json` are the first five posts of a real demo run: the Deepavali goal on the Poojaloka
catalogue snapshot (24 Oct 2026), generated on 31 Oct 2026. The content and asset ids come from a throwaway
database. All five are text-only because the demo snapshot has no promotable product with a real store photo (the
only one is a test listing); each file lists this under `data_issues`. Brief 1 is about Deepavali on 8 Nov 2026, a
date checked against the official holiday list.

Schema and rules: `backend/growthpilot/agent/briefs.py`. To load a brief strictly, use
`validate_brief(json_or_dict)`; it rejects unknown fields and broken rules.

## Fields

| Field | Meaning |
|---|---|
| `schema_version` | `"1.0"` |
| `content_id`, `platform`, `format` | The post; `format` is `single_image` or `carousel` (the size is in `canva_query`) |
| `objective`, `audience` | From the campaign (objective metric + goal) or the brand profile |
| `festival` | `{name, start, end, source}` only for a dated, verified festival that is upcoming or ongoing within 21 days of the post; otherwise `null` |
| `angle` | `festival_prep`, `product_spotlight`, `material_focus`, `category_edit`, `know_how`, `brand_promise` |
| `image_policy` | `text_only`, `may_use_images` (trust not confirmed; a person must check), `must_use_images` (a real store photo of the product, or a team upload linked to the post) |
| `image_refs` | `[{source: brand_site \| uploaded, asset_id, product_sku}]`; empty when text-only |
| `headline`, `tagline`, `cta` | At most 8, 14 and 6 words; one CTA |
| `required_text` | The only text allowed on the design; always includes `"Poojaloka"` |
| `claims_allowed` | Facts a caption may state, each traced to `product_sku` + `field` (`name`, `category`, `materials`, `dimensions`, `price`). Price appears only when the catalogue data is fresh and unflagged, and never on the poster |
| `banned` | Concepts and phrases that must not appear (offers, stock or delivery promises, purity/origin/health claims, deities/mantras/Sanskrit text, stock photos shown as the product, competitors, the brand's prohibited and restricted claims) |
| `style` | `{composition, layout, palette, colors, mood}` from the brand colours |
| `needs_human_review` | `true` when any `data_issues` entry needs review |
| `canva_query` | At most 120 words. It names Poojaloka, quotes every `required_text` item exactly, describes layout and colours, forbids extra text and claims, requires referenced photos to stay unaltered, and (for text-only) forbids product photos, deities, mantras and Sanskrit text |
| `signals` | `{trend_ids, competitor_insight_ids, reason}`. Competitor ids point to general format patterns only; no competitor text, images or names are used |
| `data_issues` | `[{code, message, needs_review}]`: missing or untrusted inputs, substitutions, retries |

## Rules worth knowing

- **Weekly mix:** each block of five posts aims for 2 text-only, 2 image-based and 1 combination. Image slots are
  filled only with trusted images. Shortfalls become text-only and are reported as `mix_shortfall`.
- **No repeats:** angle, headline, tagline, layout and palette are not repeated from the last 8 posts when an
  alternative exists. Set the window with the tool's `repeat_window` or the brand's
  `posting_constraints.brief_repeat_window`.
- **Prior QA:** failed render checks, claim checks and reviewer notes shorten the headline, simplify the layout,
  raise contrast or drop the price claim.
- **Validation and fallback:** a brief that fails validation is redone once. If it fails again, the post gets a
  flagged, text-only evergreen brief (`validation_failed`).
- **Festival dates:** these come from the brand's festival calendar (`catalogue_source.festivals[].date`) when it
  has one. Otherwise they come from `backend/growthpilot/services/festival_dates.py`, a table of dates checked
  against official holiday lists, each with its source. GrowthPilot's built-in seasonal calendar is a planning hint
  and is never used as a date. The checked dates so far:
  - Deepavali: 8 Nov 2026 (official Karnataka list) and 29 Oct 2027 (from the DoPT 2027 order)
  - Krishna Janmashtami: 4 Sep 2026, now past
  - Navaratri: none yet. The official lists give only the last day (20 Oct 2026), not the start.

## Not built yet: the Canva step

`POST /api/content/{cid}/canva-poster` doesn't exist yet, and its request and response format isn't defined here.
Whatever builds it can rely on the brief fields above.
