"""
api/routes/logs.py
==================
Endpoints for persistent log storage and per-node deploy events.

Register in main.py:
    from api.routes.logs import router as logs_router
    app.include_router(logs_router)

Routes:
  GET    /api/logs/history          — last N log lines
  DELETE /api/logs/history          — wipe log file
  GET    /api/logs/node-events      — per-node event map
  POST   /api/logs/node-events/{id} — upsert one node event (called by orchestrator)
  POST   /api/logs/append           — append one log line (called by frontend)
"""
from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from core.log_store import (
    append_log,
    clear_logs,
    read_logs,
    read_node_events,
    upsert_node_event,
    infer_node_event_from_line,
    build_node_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/deploy-logs", tags=["logs"])


# ── Log history ───────────────────────────────────────────────────────────────

@router.get("/history")
def get_log_history(limit: int = 500):
    entries = read_logs(limit=limit)
    return {"entries": entries, "total": len(entries)}


@router.delete("/history")
def delete_log_history():
    clear_logs()
    return {"ok": True}


# ── Per-node events ───────────────────────────────────────────────────────────

@router.get("/node-events")
def get_node_events():
    return read_node_events()


class NodeEventPayload(BaseModel):
    label:   str
    status:  str
    raw_log: str
    ts:      Optional[int] = None


@router.post("/node-events/{node_id}")
def post_node_event(node_id: str, body: NodeEventPayload):
    """
    Called by the orchestrator after each node completes.
    Builds a rich structured event and persists it.
    """
    event = build_node_event(
        node_id=node_id,
        label=body.label,
        status=body.status,
        raw_log=body.raw_log,
        ts=body.ts,
    )
    upsert_node_event(node_id, event)
    logger.info("node-event saved: %s → %s", node_id, body.status)
    return {"ok": True, "event": event}


# ── Append (individual log line from frontend) ────────────────────────────────

class LogLine(BaseModel):
    ts:      str
    msg:     str
    level:   str = "info"
    node_id: Optional[str] = None


@router.post("/append")
def post_append(entry: LogLine):
    rec = entry.model_dump()
    append_log(rec)

    # Try to infer a node event from terminal-outcome lines
    if entry.node_id:
        ev = infer_node_event_from_line(
            node_id=entry.node_id,
            label=entry.node_id,
            msg=entry.msg,
            level=entry.level,
        )
        if ev:
            upsert_node_event(entry.node_id, ev)

    return {"ok": True}