"""Explicit, standalone Canva MCP generation smoke test for local development.

This script is intentionally not wired into GrowthPilot. It reads one existing
workspace credential, refuses to refresh it (refresh rotation writes storage),
rolls back the client's local usage reservation, and never publishes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from growthpilot.config import get_settings
from growthpilot.creative.canva_mcp import (
    CanvaMCPClient,
    CanvaMCPError,
    _candidate_rows,
    _nested,
    generate_design_args,
    jwt_expiry,
    safe_canva_message,
)
from growthpilot.db import make_engine
from growthpilot.models import ProviderCredential
from growthpilot.security import decrypt_json

BRIEF = (
    "Create a 4:5 Instagram promotional poster for a fictional pooja store called Ember & Ritual "
    "and its fictional product ‘Evening Glow Diya Set’. Use a warm saffron and maroon palette, "
    "elegant editorial typography, simple abstract light motifs, and a clear area for a logo. "
    "Include exactly this copy: ‘Evening Glow Diya Set’; ‘A warm touch for festive moments’; "
    "‘Explore the collection’. Do not add prices, product claims, religious symbols, deity imagery, "
    "mantras, or Sanskrit text."
)
USER_INTENT = "Create one fictional, text-led Instagram promotional poster for local Canva integration testing."
TEST_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "data" / "canva-local-test-output"


class TestFlowError(RuntimeError):
    pass


def _schema(tool: Any) -> dict[str, Any]:
    raw = getattr(tool, "inputSchema", getattr(tool, "input_schema", {}))
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    return raw if isinstance(raw, dict) else {}


def _tool_description(tool: Any) -> str:
    value = getattr(tool, "description", "") or ""
    return safe_canva_message(str(value))


def _safe_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _safe_schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_schema(item) for item in value]
    if isinstance(value, str):
        return safe_canva_message(value)
    return value


def _field_value(field: str, spec: dict[str, Any], *, candidate: dict[str, Any],
                 result: dict[str, Any], design_id: str = "") -> tuple[bool, Any]:
    """Map only recognized schema properties; unknown required fields fail closed."""
    if field in candidate:
        return True, candidate[field]
    normalized = field.replace("-", "_").casefold()
    if normalized in {"candidate_id", "candidateid"}:
        value = candidate.get("candidate_id") or candidate.get("candidateId") or candidate.get("id")
        return (True, value) if value is not None else (False, None)
    if normalized in {"design_id", "designid"}:
        value = design_id or candidate.get("design_id") or candidate.get("designId")
        return (True, value) if value else (False, None)
    if normalized in {"job_id", "jobid", "export_id", "exportid"}:
        value = _nested(result, "job_id", "jobId", "export_id", "exportId")
        return (True, value) if value else (False, None)
    if normalized in {"user_intent", "intent"}:
        return True, "Commit the selected fictional Canva poster candidate as a private design."
    if "default" in spec:
        return True, spec["default"]
    return False, None


def _schema_args(tool: Any, *, candidate: dict[str, Any], result: dict[str, Any],
                 design_id: str = "") -> dict[str, Any]:
    schema = _schema(tool)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    arguments: dict[str, Any] = {}
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        found, value = _field_value(name, spec, candidate=candidate, result=result, design_id=design_id)
        if found:
            arguments[name] = value
    missing = sorted(required - set(arguments))
    if missing:
        raise TestFlowError(
            f"Cannot safely call {getattr(tool, 'name', 'Canva tool')}: schema-required fields "
            f"have no known value mapping: {', '.join(missing)}. No arguments were guessed."
        )
    return arguments


def _png_format_value(spec: dict[str, Any]) -> tuple[bool, Any]:
    enum = spec.get("enum")
    if isinstance(enum, list):
        png = next((item for item in enum if isinstance(item, str) and item.casefold() == "png"), None)
        return (True, png) if png else (False, None)
    if spec.get("type") == "object":
        props = spec.get("properties", {})
        required = set(spec.get("required", []))
        value: dict[str, Any] = {}
        for name, child in props.items():
            if name.casefold() in {"type", "format", "file_type", "output_format"} and isinstance(child, dict):
                found, choice = _png_format_value(child)
                if found:
                    value[name] = choice
        if value and not (required - set(value)):
            return True, value
    return False, None


def _export_args(tool: Any, design_id: str) -> dict[str, Any]:
    schema = _schema(tool)
    props = schema.get("properties", {})
    arguments: dict[str, Any] = {}
    design_fields = {"design_id", "designid"}
    format_fields = {"format", "export_format", "output_format", "file_type"}
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        normalized = name.replace("-", "_").casefold()
        if normalized in design_fields:
            arguments[name] = design_id
        elif normalized in format_fields:
            found, value = _png_format_value(spec)
            if found:
                arguments[name] = value
        elif normalized == "as_single_image" and spec.get("type") == "boolean":
            arguments[name] = True
        elif "default" in spec:
            arguments[name] = spec["default"]
    missing = sorted(set(schema.get("required", [])) - set(arguments))
    if missing:
        raise TestFlowError(
            "export-design is listed, but this script cannot safely map the schema-required fields: "
            + ", ".join(missing) + ". The tool schema is printed above; no arguments were guessed."
        )
    if not any(name.replace("-", "_").casefold() in format_fields for name in arguments):
        raise TestFlowError("export-design schema does not advertise a PNG format option.")
    return arguments


def _walk_for_string(data: Any, keys: set[str]) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.casefold() in keys and isinstance(value, str) and value.startswith("https://"):
                return value
        for value in data.values():
            found = _walk_for_string(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _walk_for_string(value, keys)
            if found:
                return found
    return None


def _design_id(data: Any) -> str:
    value = _nested(data, "design_id", "designId")
    if isinstance(value, str) and value:
        return value
    design = data.get("design") if isinstance(data, dict) else None
    if isinstance(design, dict) and isinstance(design.get("id"), str):
        return design["id"]
    return ""


def _edit_url(data: Any) -> str | None:
    return _walk_for_string(data, {"edit_url", "editurl"})


def _print_edit_url(url: str | None) -> None:
    if not url:
        print("Canva edit URL: unavailable in the returned response")
        return
    parsed = urlparse(url)
    trusted_host = parsed.hostname == "canva.com" or bool(parsed.hostname and parsed.hostname.endswith(".canva.com"))
    if trusted_host and parsed.scheme == "https" and not parsed.username and not parsed.password \
            and not parsed.query and not parsed.fragment:
        print("Canva edit URL:", url)
    else:
        print("Canva edit URL: [redacted access-bearing or query-bearing URL]")


async def _discover_tools(client: CanvaMCPClient) -> dict[str, Any]:
    """Read the server's complete tool list; execution still uses the client's allow-list."""
    listed = await client._session.list_tools()
    tools = getattr(listed, "tools", []) or []
    return {str(tool.name).replace("_", "-"): tool for tool in tools}


def _tool_report(tools: dict[str, Any], allowed: set[str]) -> None:
    print("Canva MCP server tools and input schemas (calls remain restricted to the existing client allow-list):")
    for name, tool in sorted(tools.items()):
        safe_schema = _safe_schema(_schema(tool))
        print(json.dumps({"name": name, "description": _tool_description(tool), "input_schema": safe_schema,
                          "callable_by_existing_client": name in allowed}, ensure_ascii=True, sort_keys=True))


async def _download_png(url: str, target: Path) -> None:
    import httpx
    from PIL import Image

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as web:
            response = await web.get(url)
        if response.is_error:
            raise TestFlowError(f"PNG download failed with HTTP {response.status_code}.")
        target.write_bytes(response.content)
        with Image.open(target) as image:
            if image.format != "PNG":
                raise TestFlowError("The export download did not contain a PNG image.")
            image.verify()
    except TestFlowError:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise TestFlowError(f"PNG download failed ({type(exc).__name__}); the signed URL was not logged.") from None


async def _export_download_url(client: CanvaMCPClient, exported: dict[str, Any], actual_tools: dict[str, Any],
                               allowed_tools: set[str], design_id: str) -> str | None:
    url = _walk_for_string(exported, {"download_url", "downloadurl", "export_url"})
    if url:
        return url
    status_tools = [name for name in actual_tools if "export" in name and ("status" in name or "job" in name)]
    callable_status_tools = [name for name in status_tools if name in allowed_tools]
    export_id = _nested(exported, "export_id", "exportId", "job_id", "jobId")
    if not export_id:
        raise TestFlowError("export-design returned no download URL and no recognizable export/job identifier.")
    if not callable_status_tools:
        if status_tools:
            raise TestFlowError(
                "export-design returned an asynchronous job, but its status tool is blocked by the existing "
                f"client allow-list (server-advertised: {', '.join(sorted(status_tools))})."
            )
        return None

    status_name = sorted(callable_status_tools)[0]
    status_tool = client.tools[status_name]
    start = time.monotonic()
    while time.monotonic() - start < 120:
        args = _schema_args(status_tool, candidate={}, result=exported, design_id=design_id)
        status = await client.call(status_name, args)
        url = _walk_for_string(status, {"download_url", "downloadurl", "export_url"})
        if url:
            return url
        state = str(_nested(status, "status", "state", "job_status") or "").casefold()
        if state in {"failed", "error", "cancelled", "canceled"}:
            raise TestFlowError(f"Canva export job ended with status {state}.")
        await asyncio.sleep(3)
    raise TestFlowError("Canva export status polling exceeded the 120-second limit.")


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    redirect = settings.canva_callback_uri
    if not (settings.canva_client_id and settings.canva_client_secret):
        raise TestFlowError("Canva OAuth app configuration is missing (client ID or client secret).")
    if urlparse(redirect).scheme != "https" or not urlparse(redirect).hostname:
        raise TestFlowError("CANVA_REDIRECT_URI must be the exact registered public HTTPS callback URL.")

    engine = make_engine(settings.database_url)
    output_dir = TEST_OUTPUT_ROOT / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3))
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        with Session(engine) as db:
            try:
                statement = select(ProviderCredential).where(ProviderCredential.provider == "canva_mcp")
                if args.workspace_id is not None:
                    statement = statement.where(ProviderCredential.workspace_id == args.workspace_id)
                rows = db.execute(statement.order_by(ProviderCredential.workspace_id)).scalars().all()
            except OperationalError:
                raise TestFlowError(
                    "The configured database has no readable Canva credential table. Apply the reviewed "
                    "credential migration before running this test; this script will not run migrations."
                ) from None
            if not rows:
                raise TestFlowError("No saved Canva MCP credentials exist for the selected workspace.")
            if len(rows) != 1:
                raise TestFlowError("More than one workspace has Canva credentials; pass --workspace-id explicitly.")

            row = rows[0]
            tokens = decrypt_json(row.credentials_enc)
            access_token = tokens.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise TestFlowError("The encrypted workspace credential has no access token.")
            expiry = jwt_expiry(access_token)
            if expiry and expiry.timestamp() <= datetime.now(UTC).timestamp() + 300:
                raise TestFlowError(
                    "The saved access token is expired or expires within five minutes. Reconnect or verify "
                    "Canva in the app first; this no-database-write test will not rotate tokens."
                )

            print("Using the already-authorized workspace credential; token refresh and database writes are disabled.")
            try:
                async with CanvaMCPClient(access_token, db=db, mcp_url=settings.canva_mcp_url) as client:
                    actual_tools = await _discover_tools(client)
                    allowed_tools = set(client.tools)
                    _tool_report(actual_tools, allowed_tools)
                    generator = client.tools.get("generate-design")
                    if generator is None:
                        if "generate-design" in actual_tools:
                            raise TestFlowError("generate-design exists on Canva but is blocked by the existing client allow-list.")
                        raise TestFlowError("Canva MCP did not expose generate-design in its authenticated tool list.")
                    generation_args = generate_design_args(generator, query=BRIEF, user_intent=USER_INTENT)
                    generated = await client.call("generate-design", generation_args)
                    job_id = _nested(generated, "job_id", "jobId")
                    if job_id and not ({"get-design-candidates", "get-create-design-async-job"} & allowed_tools):
                        advertised = sorted({"get-design-candidates", "get-create-design-async-job"} & set(actual_tools))
                        raise TestFlowError(
                            "generate-design returned an asynchronous job, but no candidate/status polling tool "
                            f"is callable by the existing client (server-advertised: {advertised or 'none'})."
                        )
                    result = await client.poll_design_job(generated, max_seconds=120)
                    candidates = _candidate_rows(result) or _candidate_rows(generated)
                    if not candidates:
                        raise TestFlowError(
                            "Generation returned no candidate rows in the supported response shape; "
                            "no candidate was selected or committed."
                        )
                    selected = candidates[0]
                    candidate_id = selected.get("candidate_id") or selected.get("candidateId") or selected.get("id")
                    print("Generated candidate count:", len(candidates))
                    print("Selected candidate:", str(candidate_id) if candidate_id else "candidate identifier unavailable")

                    commit_tool = client.tools.get("create-design-from-candidate")
                    if commit_tool is None:
                        suffix = " It is blocked by the existing client allow-list." \
                            if "create-design-from-candidate" in actual_tools else ""
                        raise TestFlowError(
                            "Canva generated candidates, but create-design-from-candidate is unavailable; "
                            "no editable design can be committed or exported." + suffix
                        )
                    commit_args = _schema_args(commit_tool, candidate=selected, result=result)
                    committed = await client.call("create-design-from-candidate", commit_args)
                    design_id = _design_id(committed)
                    if not design_id:
                        raise TestFlowError(
                            "Candidate commit returned no recognizable design_id; the returned response "
                            "was not printed because it may contain access-bearing URLs."
                        )
                    print("Canva design ID:", design_id)
                    _print_edit_url(_edit_url(committed))

                    export_tool = client.tools.get("export-design")
                    if export_tool is None:
                        suffix = " It is blocked by the existing client allow-list." if "export-design" in actual_tools else ""
                        raise TestFlowError("The authenticated Canva MCP tool list does not include callable export-design." + suffix)
                    export_args = _export_args(export_tool, design_id)
                    exported = await client.call("export-design", export_args)
                    download_url = await _export_download_url(client, exported, actual_tools, allowed_tools, design_id)
                    if not download_url:
                        raise TestFlowError(
                            "export-design returned no immediate download URL, and no callable export-status "
                            "tool was advertised by Canva. This client cannot retrieve an asynchronous export."
                        )
                    png_path = output_dir / "fictional-ember-and-ritual-poster.png"
                    await _download_png(download_url, png_path)
                    print("PNG saved:", png_path)
            finally:
                # CanvaMCPClient reserves generation usage in this session; discard it with every
                # other local transaction so this test never changes GrowthPilot records.
                db.rollback()
    finally:
        engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, help="Required only when multiple workspaces have Canva credentials.")
    parser.add_argument("--confirm-canva-generation", action="store_true",
                        help="Required: generation and candidate commit create designs in the authorized Canva account.")
    args = parser.parse_args()
    if not args.confirm_canva_generation:
        print("No calls made. Re-run with --confirm-canva-generation only after approving the live Canva test.")
        return 2
    try:
        return asyncio.run(run(args))
    except CanvaMCPError as exc:
        print("Canva test stopped:", safe_canva_message(str(exc)), file=sys.stderr)
    except TestFlowError as exc:
        print("Canva test stopped:", safe_canva_message(str(exc)), file=sys.stderr)
    except Exception as exc:  # no exception text: third-party errors can contain signed URLs
        print("Canva test stopped:", type(exc).__name__, "(details suppressed for credential safety).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
