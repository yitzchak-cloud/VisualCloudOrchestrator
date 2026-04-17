"""
Visual Cloud Orchestrator — FastAPI Backend
Run: uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nodes import (
    CloudRunNode, CloudSQLNode, PubsubNode,
    GCSBucketNode, ServiceAccountNode, VirtualPrivateCloudNode, SecretManagerNode,
    SubscriptionNode
)

# ── Registry ──────────────────────────────────────────────────────────────────

NODE_REGISTRY: dict[str, type] = {
    cls.__name__: cls for cls in [
        CloudRunNode, CloudSQLNode, PubsubNode,
        GCSBucketNode, ServiceAccountNode, VirtualPrivateCloudNode, SecretManagerNode, SubscriptionNode
    ]
}

STATE_FILE = Path("state/desired.yaml")
ACTUAL_FILE = Path("state/actual.yaml")
STATE_FILE.parent.mkdir(exist_ok=True)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="VCO API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

# ── Models ────────────────────────────────────────────────────────────────────

class GraphPayload(BaseModel):
    nodes: list[dict]
    edges: list[dict]

class EdgeValidation(BaseModel):
    source_type: str
    target_type: str

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/node-types")
def get_node_types():
    """Return all node schemas — React Flow reads this on startup."""
    return [cls.ui_schema() for cls in NODE_REGISTRY.values()]


@app.post("/api/validate-edge")
def validate_edge(body: EdgeValidation):
    """Check if connecting two ports is legal."""
    valid = body.source_type == body.target_type
    return {"valid": valid, "reason": None if valid else f"Cannot connect {body.source_type} → {body.target_type}"}


@app.get("/api/state")
def get_state():
    """Return current desired state YAML as JSON."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return yaml.safe_load(f) or {}
    return {}


@app.post("/api/graph")
async def save_graph(payload: GraphPayload):
    """Save graph to desired.yaml and notify all WS clients."""
    # Enrich each node with its current deployed status from actual state
    actual = _load_actual()
    actual_ids: set[str] = set(actual.get("node_ids", []))

    nodes_with_status = []
    for n in payload.nodes:
        n_copy = dict(n)
        n_copy["deployed"] = n["id"] in actual_ids
        nodes_with_status.append(n_copy)

    state = {
        "nodes": nodes_with_status,
        "edges": payload.edges,
    }
    with open(STATE_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    await manager.broadcast({"event": "graph_saved", "node_count": len(payload.nodes)})
    return {"status": "saved"}


def _load_actual() -> dict:
    """Load the actual (deployed) state from disk."""
    if ACTUAL_FILE.exists():
        with open(ACTUAL_FILE) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_actual(state: dict):
    ACTUAL_FILE.parent.mkdir(exist_ok=True)
    with open(ACTUAL_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True)


async def _log(msg: str, level: str = "info"):
    """Broadcast a log line with level so the UI can colour it."""
    await manager.broadcast({"event": "log", "msg": msg, "level": level})


@app.post("/api/deploy")
async def deploy(payload: GraphPayload):
    """
    Diff-based deployment simulation.
    Compares desired graph against actual.yaml to determine:
      - new nodes   → deploy
      - changed nodes → update
      - removed nodes → destroy
    Sends typed WebSocket events so the UI can colour each log line.
    """
    desired_ids: set[str] = {n["id"] for n in payload.nodes}

    actual = _load_actual()
    actual_ids: set[str] = set(actual.get("node_ids", []))
    actual_props: dict[str, Any] = actual.get("node_props", {})

    to_create  = [n for n in payload.nodes if n["id"] not in actual_ids]
    to_update  = [n for n in payload.nodes if n["id"] in actual_ids
                  and actual_props.get(n["id"]) != n.get("props", {})]
    to_destroy = [nid for nid in actual_ids if nid not in desired_ids]

    total = len(to_create) + len(to_update) + len(to_destroy)

    if total == 0:
        await _log("Nothing to deploy — state is already up to date.", "ok")
        await manager.broadcast({"event": "deploy_complete", "changed": 0})
        return {"status": "no_change"}

    await manager.broadcast({"event": "deploy_started", "total": total,
                              "create": len(to_create),
                              "update": len(to_update),
                              "destroy": len(to_destroy),
                              "touched_ids": (
                                  [n["id"] for n in to_create] +
                                  [n["id"] for n in to_update] +
                                  to_destroy
                              )})
    await _log(f"Plan: {len(to_create)} to create, {len(to_update)} to update, "
               f"{len(to_destroy)} to destroy", "info")

    index = 0

    # ── DESTROY removed nodes ──────────────────────────────────────────────
    for nid in to_destroy:
        index += 1
        await asyncio.sleep(0.6)
        await _log(f"[{index}/{total}] {nid} → destroyed", "warn")
        await manager.broadcast({
            "event": "node_status", "node_id": nid,
            "status": "destroyed", "index": index, "total": total,
        })

    # ── UPDATE changed nodes ───────────────────────────────────────────────
    for node in to_update:
        index += 1
        await asyncio.sleep(0.7)
        label = node.get("label") or node["id"]
        await _log(f"[{index}/{total}] {label} → updated", "info")
        await manager.broadcast({
            "event": "node_status", "node_id": node["id"],
            "status": "deployed", "action": "update",
            "index": index, "total": total,
        })

    # ── CREATE new nodes ───────────────────────────────────────────────────
    for node in to_create:
        index += 1
        await asyncio.sleep(0.8)
        label = node.get("label") or node["id"]
        await _log(f"[{index}/{total}] {label} → deployed", "ok")
        await manager.broadcast({
            "event": "node_status", "node_id": node["id"],
            "status": "deployed", "action": "create",
            "index": index, "total": total,
        })

    # ── Persist new actual state ───────────────────────────────────────────
    _save_actual({
        "node_ids":   list(desired_ids),
        "node_props": {n["id"]: n.get("props", {}) for n in payload.nodes},
    })

    # ── Notify UI about unchanged nodes (already deployed) ─────────────────
    unchanged_ids = desired_ids - {n["id"] for n in to_create} - {n["id"] for n in to_update}
    for nid in unchanged_ids:
        await manager.broadcast({
            "event": "node_status", "node_id": nid,
            "status": "deployed", "action": "unchanged",
        })

    await _log("Deploy complete ✓", "ok")
    await manager.broadcast({"event": "deploy_complete", "changed": total})
    return {"status": "ok", "changed": total}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)