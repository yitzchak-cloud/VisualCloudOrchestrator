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
    CloudRunNode, CloudSQLNode, PubSubNode,
    GCSBucketNode, ServiceAccountNode, VPCNode, SecretManagerNode,
)

# ── Registry ──────────────────────────────────────────────────────────────────

NODE_REGISTRY: dict[str, type] = {
    cls.__name__: cls for cls in [
        CloudRunNode, CloudSQLNode, PubSubNode,
        GCSBucketNode, ServiceAccountNode, VPCNode, SecretManagerNode,
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
    state = {
        "nodes": payload.nodes,
        "edges": payload.edges,
    }
    with open(STATE_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    await manager.broadcast({"event": "graph_saved", "node_count": len(payload.nodes)})
    return {"status": "saved"}


@app.post("/api/deploy")
async def deploy(payload: GraphPayload):
    """Simulate deployment — in production wires to Terraform runner."""
    await manager.broadcast({"event": "deploy_started", "total": len(payload.nodes)})

    for i, node in enumerate(payload.nodes):
        await asyncio.sleep(0.8)  # replace with real terraform apply
        status = "deployed"
        await manager.broadcast({
            "event":   "node_status",
            "node_id": node["id"],
            "status":  status,
            "index":   i + 1,
            "total":   len(payload.nodes),
        })

    await manager.broadcast({"event": "deploy_complete"})
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)
