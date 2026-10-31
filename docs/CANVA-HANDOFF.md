# Creative brief to Canva handoff

The planner continues to use `growthpilot.agent.briefs.CreativeBrief` schema `1.0` as its canonical, validated and approval-versioned representation. It is saved in `content_items.creative_brief`. Do not create a second planner or write a competing brief field.

## Adapter

Call `growthpilot.agent.briefs.to_canva_handoff(brief)` after loading and validating the canonical model. The adapter is pure and makes no network requests. It exposes the Canva fields (`schema_version` as integer `1`, `content_id`, `platform`, `format`, `objective`, `audience`, `festival`, `angle`, `image_policy`, `image_refs`, `headline`, `tagline`, `cta`, `required_text`, `claims_allowed`, `banned`, `style`, `needs_human_review`, `canva_query`, `signals`) and retains the full canonical brief and structured claim evidence in `canonical` and `claim_evidence`.

`single_image` maps to `instagram_post`; `carousel` maps to `carousel_slide`. The current canonical schema does not represent Stories, so the adapter does not invent a Story format. Image references carry their source, asset ID, SKU when known, and trust classification. A brand-site image must be `real_match` to qualify as required imagery; unknown references remain explicitly unknown. Uploaded assets remain references by ID, not URL-only prompt text.

`claims_allowed` at the handoff boundary is a list of validated claim text for consumers expecting strings. The evidence objects (`text`, `product_sku`, `field`, `value`) are retained separately and in `canonical`; consumers should use those facts and never treat an unsupported string as approved claim evidence.

## Expected endpoint boundary

This repository currently has no `POST /api/content/{cid}/canva-poster` route. The future endpoint should accept the adapter payload and return a job/result envelope containing `content_id`, `status`, `mode`, optional `image_skip_reason`, `design_id`, an ephemeral edit URL for UI display, local preview/export asset reference, QA verdict/issues and sanitized error information. The planner must not claim a design exists until that service reports completion. Do not persist or log signed URLs, and do not publish from this handoff.

## Safety and human review

The canonical writer validates product claims against structured product evidence, excludes competitor names from copy, filters festivals to verified dates within 21 days, avoids generic stock as a product photo, and records previous QA issues. If a trend or content context requires religious imagery, `needs_human_review` must be honored; the prompt must not request deities, mantras or Sanskrit text. A reviewer must inspect religious imagery/symbols before approval. Text-only requests remain explicitly text-only, and image IDs must refer to the actual uploaded/catalogue assets.
