"""
api/routes/realtime.py
======================
/api/logs/{node_id}  — SSE stream of real GCP logs for a deployed node
/ws                  — WebSocket endpoint (all deploy/graph events)

The SSE endpoint works in three steps:
  1. Read the node's Pulumi outputs from state (uri, name, id…).
  2. Ask the node itself (node.log_source()) for the Cloud Logging filter.
  3. Poll the Cloud Logging API and stream matching entries to the client.

Query params for /api/logs/{node_id}:
  stack     — Pulumi stack name (default "dev")
  interval  — poll interval in seconds (default 3, min 1)
  page_size — log entries per poll (default 30)

SSE event format:
  data: {"ts": "…", "severity": "INFO", "text": "…", "insertId": "…"}\n\n

  or on error / no logs configured:
  data: {"type": "meta", "msg": "…"}\n\n
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from core.registry import NODE_REGISTRY
from core.state import STACK_DIR
from core.ws_manager import manager
from deploy.state_reader import read_actual_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])


# import os
# from core.state import STACK_DIR

# # הגדרת ה-Backend לנתיב שבו ה-Orchestrator שומר את המידע
# if not os.environ.get("PULUMI_BACKEND_URL"):
#     os.environ["PULUMI_BACKEND_URL"] = f"file://{STACK_DIR.absolute()}"

# # מומלץ גם לוודא שה-Passphrase מוגדר אם השתמשת בכזה
# if not os.environ.get("PULUMI_CONFIG_PASSPHRASE"):
#     os.environ["PULUMI_CONFIG_PASSPHRASE"] = ""

# ── Cloud Logging poller ───────────────────────────────────────────────────────

async def _poll_cloud_logs(
    log_filter: str,
    project:    str,
    page_size:  int,
    seen_ids:   set[str],
) -> list[dict]:
    """
    Query Cloud Logging for entries matching *log_filter*.
    Returns only entries not yet in *seen_ids*.
    Updates *seen_ids* in-place.

    Runs the synchronous google-cloud-logging call in a thread executor
    so it never blocks the FastAPI event loop.
    """
    import asyncio
    loop = asyncio.get_event_loop()

    def _fetch():
        # Import here so the dependency is optional at module load time
        from google.cloud import logging as gcloud_logging 

        client  = gcloud_logging.Client(project=project)
        entries = client.list_entries(
            filter_=log_filter,
            order_by=gcloud_logging.DESCENDING,
            page_size=page_size,
        )
        results = []
        for entry in entries:
            iid = entry.insert_id or ""
            if iid and iid in seen_ids:
                continue
            seen_ids.add(iid)
            payload = entry.payload
            if isinstance(payload, dict):
                text = payload.get("message") or json.dumps(payload)
            elif hasattr(payload, "message"):
                text = payload.message
            else:
                text = str(payload)

            results.append({
                "ts":       entry.timestamp.isoformat() if entry.timestamp else "",
                "severity": entry.severity or "DEFAULT",
                "text":     text,
                "insertId": iid,
            })
        return list(reversed(results))   # oldest first for display

    return await loop.run_in_executor(None, _fetch)


# ── SSE generator ─────────────────────────────────────────────────────────────

async def _generate_log_stream(
    node_id:   str,
    stack:     str,
    interval:  float,
    page_size: int,
) -> AsyncIterator[str]:
    """
    Main SSE generator.  Resolves the node's log_source, then polls
    Cloud Logging in a loop, yielding new entries as SSE events.
    """

    def _meta(msg: str) -> str:
        return f"data: {json.dumps({'type': 'meta', 'msg': msg})}\n\n"

    def _entry(e: dict) -> str:
        return f"data: {json.dumps(e)}\n\n"

    # ── Step 1: look up node's Pulumi outputs from local stack state ──────────
    actual   = read_actual_state(str(STACK_DIR), stack)
    node_info = actual.get("nodes", {}).get(node_id)

    if node_info is None:
        yield _meta(f"Node '{node_id}' has not been deployed yet.")
        return

    pulumi_outputs = node_info.get("outputs", {})
    status         = node_info.get("status", "unknown")

    if status != "deployed":
        yield _meta(f"Node '{node_id}' status is '{status}' — no logs available.")
        return

    # ── Step 2: ask the node class for its log_source ─────────────────────────
    # We need the project from the Pulumi stack config — fall back to env
    import os
    project = os.environ.get("GCP_PROJECT", "")
    region  = os.environ.get("GCP_REGION", "us-central1")

    # Try to read project from stack config
    try:
        from deploy.pulumi_helpers import get_pulumi_command, make_workspace_opts
        from pathlib import Path
        from pulumi import automation as auto
        import re

        safe_id   = re.sub(r"[^a-zA-Z0-9_]", "-", node_id)
        node_dir  = Path(STACK_DIR) / safe_id
        full_name = f"{stack}-{safe_id}"
        if node_dir.exists():
            cmd = get_pulumi_command(Path(STACK_DIR))
            so  = auto.create_or_select_stack(
                stack_name=full_name,
                project_name="vco-stack",
                program=lambda: None,
                opts=make_workspace_opts(node_dir, cmd),
            )
            cfg     = so.get_all_config()
            print("cfg:", cfg , "--------------------------------------")
            project = cfg.get("gcp:project", auto.ConfigValue(value=project)).value
            region  = cfg.get("gcp:region",  auto.ConfigValue(value=region)).value
    except Exception as exc:
        logger.debug("log_stream: could not read stack config for %s — %s", node_id, exc)

    if not project:
        yield _meta("GCP project not configured. Set GCP_PROJECT env var or deploy first.")
        return

    # Find the node class and call log_source()
    node_type = None
    # node_id is not the type; scan saved graph for the matching node
    try:
        import yaml
        from core.state import STATE_FILE
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                saved = yaml.safe_load(f) or {}
            for n in saved.get("nodes", []):
                if n.get("id") == node_id:
                    node_type = n.get("type")
                    break
    except Exception as exc:
        logger.debug("log_stream: could not read state file — %s", exc)

    cls = NODE_REGISTRY.get(node_type or "")
    if cls is None:
        yield _meta(f"Unknown node type '{node_type}' — cannot determine log source.")
        return

    node_inst = cls(node_id=node_id, label="")
    log_src   = node_inst.log_source(pulumi_outputs, project, region)

    if log_src is None:
        yield _meta(f"Node type '{node_type}' does not expose a Cloud Logging stream.")
        return

    # Override project if log_source returned one
    if log_src.project:
        project = log_src.project

    yield _meta(
        f"Streaming logs for {node_type} ({node_id}) "
        f"| project={project} "
        f"| filter: {log_src.filter[:120]}{'…' if len(log_src.filter) > 120 else ''}"
    )

    # ── Step 3: poll Cloud Logging ─────────────────────────────────────────────
    seen_ids: set[str] = set()

    while True:
        try:
            entries = await _poll_cloud_logs(
                log_filter=log_src.filter,
                project=project,
                page_size=page_size or log_src.page_size,
                seen_ids=seen_ids,
            )
            for e in entries:
                yield _entry(e)

            if not entries:
                # Send a keep-alive comment so the connection stays open
                yield ": heartbeat\n\n"

        except Exception as exc:
            logger.warning("log_stream: Cloud Logging error for %s — %s", node_id, exc)
            yield _meta(f"Cloud Logging error: {exc}")

        await asyncio.sleep(max(1.0, interval))


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/api/logs/{node_id}")
async def stream_logs(
    node_id:   str,
    stack:     str   = "dev",
    interval:  float = 3.0,
    page_size: int   = 30,
):
    """
    Server-Sent Events stream of real GCP Cloud Logging entries for a node.

    Each event is a JSON object:
      {"ts": "2024-…", "severity": "INFO", "text": "…", "insertId": "…"}

    Meta/error events:
      {"type": "meta", "msg": "…"}

    The stream polls Cloud Logging every *interval* seconds and yields
    only new entries (deduplicated by insertId).
    """
    logger.debug("SSE log stream opened: node=%s  stack=%s", node_id, stack)

    return StreamingResponse(
        _generate_log_stream(node_id, stack, interval, page_size),
        media_type="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Primary real-time channel for all deploy / graph events.
    Client messages are silently ignored (pub-sub pattern).
    """
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as exc:
        logger.warning("Unexpected WS error: %s", exc)
        manager.disconnect(ws)