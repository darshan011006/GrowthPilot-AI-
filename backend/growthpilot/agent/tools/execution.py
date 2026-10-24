from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from ...models import ChannelConnection, ConnectionStatus, ContentStatus, utcnow
from ...services import content as content_service
from ...services import publishing
from ...services.errors import WorkflowError
from ..registry import Permission, ToolBlocked, ToolContext, ToolError, ToolResult, tool
from .common import items
from .creative import ContentIdsIn


@tool("request_approval", "Send validated items to the human Approval Inbox and pause the run until a person "
      "reviews them. Items with validation failures stay as drafts with the reasons.", ContentIdsIn,
      Permission.APPROVAL)
def request_approval(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    submitted, held, already = [], [], []
    for item in items(ctx, inp.content_ids):
        if item.status == ContentStatus.IN_REVIEW:
            already.append(item.id)
            continue
        if item.status not in (ContentStatus.DRAFT, ContentStatus.CHANGES_REQUESTED):
            continue
        v = item.validation or {}
        if v.get("version") != item.version or not v.get("ok"):
            fails = [c["message"] for s in ("product_claims", "brand", "platform") for c in v.get(s, [])
                     if c.get("status") == "fail"]
            item.review_note = "Held back by the agent: " + ("; ".join(fails) or "not validated")
            held.append({"content_id": item.id, "reasons": fails})
            continue
        content_service.submit(ctx.db, item, user_id=None, role="editor")
        submitted.append(item.id)
    ctx.remember("approval_requested", True)
    ctx.remember("awaiting_ids", submitted + already)
    return ToolResult(f"{len(submitted) + len(already)} item(s) waiting in the Approval Inbox"
                      + (f"; {len(held)} held back for edits." if held else "."),
                      {"submitted": submitted, "already_in_review": already, "held": held})


def _connection(ctx: ToolContext, platform: str) -> ChannelConnection:
    conns = ctx.db.execute(select(ChannelConnection).where(
        ChannelConnection.workspace_id == ctx.workspace_id, ChannelConnection.platform == platform,
        ChannelConnection.status.in_([ConnectionStatus.CONNECTED, ConnectionStatus.DEMO]))).scalars().all()
    from ...adapters import available_adapters

    allowed = available_adapters()
    conns = [c for c in conns if c.adapter in allowed]
    if not conns:
        raise ToolBlocked(f"No verified {platform} connection available in this mode. Connect one on the "
                          "Integrations page.", blocker=f"{platform}_not_connected")
    return conns[0]


@tool("schedule_publication", "Schedule items that a person has approved, at their planned times, on a verified "
      "connection. Never schedules unapproved content; live accounts also need owner publish authorisation and "
      "LIVE_PUBLISHING_ENABLED.", ContentIdsIn, Permission.PUBLISH)
def schedule_publication(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    scheduled, skipped = [], []
    for item in items(ctx, inp.content_ids):
        if item.status != ContentStatus.APPROVED:
            skipped.append({"content_id": item.id, "reason": f"status is {item.status}"})
            continue
        conn = _connection(ctx, item.platform)
        when = item.planned_at if item.planned_at and item.planned_at > utcnow() else utcnow() + timedelta(minutes=5)
        try:
            content_service.schedule(ctx.db, item, conn, when, user_id=None, role="agent", confirmed=False,
                                     actor="agent")
            scheduled.append({"content_id": item.id, "at": when.isoformat(), "connection": conn.name})
        except WorkflowError as exc:
            skipped.append({"content_id": item.id, "reason": str(exc)})
    return ToolResult(f"Scheduled {len(scheduled)} approved item(s); skipped {len(skipped)}.",
                      {"scheduled": scheduled, "skipped": skipped})


class PublishIn(ContentIdsIn):
    pass


@tool("publish_content", "Publish already-scheduled, human-approved items immediately through their adapter. "
      "Refuses anything not approved and scheduled.", PublishIn, Permission.PUBLISH)
def publish_content(ctx: ToolContext, inp: PublishIn) -> ToolResult:
    results = []
    for item in items(ctx, inp.content_ids):
        if item.status != ContentStatus.SCHEDULED:
            results.append({"content_id": item.id, "result": f"refused: status is {item.status}"})
            continue
        item.scheduled_at = utcnow()
        ctx.db.flush()
        publishing.publish_item(ctx.db, item.id)
        ctx.db.refresh(item)
        results.append({"content_id": item.id, "result": item.status, "external_id": item.external_id,
                        "verified": item.publish_verified, "error": item.last_error})
    if not results:
        raise ToolError("Nothing to publish.")
    ok = sum(1 for r in results if r["result"] == "published")
    return ToolResult(f"Published {ok}/{len(results)}.", {"results": results},
                      is_mock=ctx.settings.is_demo)


@tool("verify_publication_status", "Ask the platform whether published items really exist (Instagram media lookup; "
      "simulated in demo mode).", ContentIdsIn, Permission.READ)
def verify_publication_status(ctx: ToolContext, inp: ContentIdsIn) -> ToolResult:
    rows = []
    for item in items(ctx, inp.content_ids):
        if item.status != ContentStatus.PUBLISHED:
            rows.append({"content_id": item.id, "state": f"not published ({item.status})"})
            continue
        rows.append({"content_id": item.id, "state": publishing.verify(ctx.db, item), "url": item.external_url})
    ok = sum(1 for r in rows if r["state"] == "published")
    return ToolResult(f"{ok}/{len(rows)} confirmed by the provider.", {"results": rows}, is_mock=ctx.settings.is_demo)
