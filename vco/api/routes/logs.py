"""
api/routes/logs.py
==================
Endpoints for persistent log storage and per-node deploy events.
All endpoints are namespace-scoped via the ?namespace= query parameter
(or the node_id path parameter already carries context).

Routes:
  GET    /api/deploy-logs/history          — last N log lines
  DELETE /api/deploy-logs/history          — wipe log file
  GET    /api/deploy-logs/node-events      — per-node event map
  POST   /api/deploy-logs/node-events/{id} — upsert one node event
  POST   /api/deploy-logs/append           — append one log line (from frontend)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.log_store import (
    append_log,
    build_node_event,
    clear_logs,
    infer_node_event_from_line,
    read_logs,
    read_node_events,
    upsert_node_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/deploy-logs", tags=["logs"])


# ── Log history ───────────────────────────────────────────────────────────────

@router.get("/history")
def get_log_history(limit: int = 500, namespace: str = "default"):
    entries = read_logs(limit=limit, namespace=namespace)
    return {"entries": entries, "total": len(entries), "namespace": namespace}


@router.delete("/history")
def delete_log_history(namespace: str = "default"):
    clear_logs(namespace=namespace)
    return {"ok": True, "namespace": namespace}


# ── Per-node events ───────────────────────────────────────────────────────────

@router.get("/node-events")
def get_node_events(namespace: str = "default"):
    return read_node_events(namespace=namespace)


class NodeEventPayload(BaseModel):
    label:     str
    status:    str
    raw_log:   str
    ts:        Optional[int] = None
    namespace: str = "default"


@router.post("/node-events/{node_id}")
def post_node_event(node_id: str, body: NodeEventPayload):
    """Called by the orchestrator after each node completes."""
    event = build_node_event(
        node_id=node_id,
        label=body.label,
        status=body.status,
        raw_log=body.raw_log,
        ts=body.ts,
    )
    upsert_node_event(node_id, event, namespace=body.namespace)
    logger.info("node-event saved: namespace=%s  %s → %s", body.namespace, node_id, body.status)
    return {"ok": True, "event": event}


# ── Append (individual log line from frontend) ────────────────────────────────

class LogLine(BaseModel):
    ts:        str
    msg:       str
    level:     str = "info"
    node_id:   Optional[str] = None
    namespace: str = "default"


@router.post("/append")
def post_append(entry: LogLine):
    rec = entry.model_dump()
    append_log(rec, namespace=entry.namespace)

    if entry.node_id:
        ev = infer_node_event_from_line(
            node_id=entry.node_id,
            label=entry.node_id,
            msg=entry.msg,
            level=entry.level,
        )
        if ev:
            upsert_node_event(entry.node_id, ev, namespace=entry.namespace)

    return {"ok": True}