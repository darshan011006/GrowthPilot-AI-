# Canva poster workflow

GrowthPilot uses the saved, canonical `CreativeBrief` and its `to_canva_handoff()` adapter. It does not create a second planner. Poster generation is private: the result enters the existing human review and approval workflow; the poster worker never publishes to a social network.

## Inputs and design rules

- The content item must have a valid saved brief for its platform and content ID.
- The brief supplies the exact headline, tagline, CTA, required text, approved claims, image policy, product image references, and Canva query.
- Product claim evidence is rechecked against the content item's workspace and selected product records before enqueueing.
- Brand name, tone/voice, palette, and optional logo come from the associated brand record. When a valid logo asset exists, it is attached through the discovered MCP upload schema; otherwise Canva is asked to use a text wordmark.
- Only uploaded or verified `real_match` product photos are sent as product imagery. Stock and placeholder assets are excluded. An optional product image that cannot be attached is recorded as skipped; `must_use_images` fails instead.
- Logo attachments are brand identity assets and do not count as product photography.

## API contract

### Enqueue

`POST /api/content/{content_id}/canva-poster` requires an editor role and a valid saved brief. No request body is required. It returns immediately:

```json
{"job_id": 42, "status": "queued", "calls_used": 0}
```

Repeated requests reuse the existing active or completed job. A failed job can be retried through the same endpoint, subject to the retained generation caps: three generations per job and `CANVA_MCP_DAILY_CAP` per day (default 10).

### Status and preview

`GET /api/content/{content_id}/canva-poster` returns the job and any committed poster record:

```json
{
  "job": {"id": 42, "status": "qa", "calls_used": 1, "error": ""},
  "poster": {"job_id": 42, "design_id": "…", "asset_id": 91, "qa": {"passed": false, "status": "REQUIRES_HUMAN_REVIEW", "issues": []}}
}
```

Statuses are `queued`, `generating`, `exporting`, `qa`, `completed`, or `failed`. On completion the content item is set to `in_review`, the PNG is stored through the regular asset service, and `asset_id` is attached to the content item. Its existing asset URL (`/api/assets/{asset_id}/file`) can be used by the content preview, approval hash, and publishing workflow.

If Canva commits a design but both export paths fail, the failed job still retains the design ID. The UI can request a short-lived edit URL through `GET /api/content/{content_id}/canva-poster/edit-link`. Edit URLs and signed download URLs are never stored.

## Export behavior

The worker first calls the allow-listed MCP `export-design` tool and searches all nested response fields for HTTPS download URLs. If no valid PNG is available, it tries the Canva REST export job (`POST /rest/v1/exports`, poll its export ID, then download the PNG). A failed export remains failed; it is never represented as a successful PNG.

The REST bearer-token adapter in `growthpilot.services.canva_rest_dev` is **development-only**. It reads `CANVA_API_TOKEN` and `CANVA_REFRESH_TOKEN`; after a REST 401 it uses the existing OAuth refresh implementation with `CANVA_CLIENT_ID` and `CANVA_CLIENT_SECRET`, and atomically rotates both token names in the repository-root `.env` before retrying the request. This fallback is blocked when `APP_ENV=production`. Do not use these manual REST tokens in deployment; use the workspace OAuth/MCP integration there. This hackathon fallback does not add a REST OAuth connect flow.

## QA, fallback and approval

The poster record stores deterministic checks and QA issues. Exported-image OCR, contrast, product-photo fidelity, and religious imagery inspection are not automated yet, so the current result remains `REQUIRES_HUMAN_REVIEW` and is never marked passed. Check the PNG in the approval flow before approving it.

When Canva is disconnected or a job fails, the content page offers GrowthPilot's existing built-in renderer (`POST /api/content/{content_id}/creative`) as an explicit fallback. It uses the brand's configured logo/palette and its existing real-photo and product-claim safeguards.

No migration is introduced by this workflow change. The existing Canva job migration and content asset service are reused.
