"""
Visual Cloud Orchestrator — FastAPI Backend
Run: uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import importlib
import pkgutil
import inspect
import nodes
from base_node import GCPNode
from pulumi_synth import synthesize_and_deploy, synthesize_only, read_actual_state

def discover_nodes() -> dict[str, type]:
    registry = {}
    for loader, module_name, is_pkg in pkgutil.walk_packages(nodes.__path__, nodes.__name__ + "."):
        module = importlib.import_module(module_name)
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, GCPNode) and obj is not GCPNode:
                registry[obj.__name__] = obj
    return registry


NODE_REGISTRY = discover_nodes()
print(f"Loaded {len(NODE_REGISTRY)} nodes: {list(NODE_REGISTRY.keys())}")

STATE_FILE = Path("state/desired.yaml")
STACK_DIR  = Path("state/pulumi_stack")
STATE_FILE.parent.mkdir(exist_ok=True)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="VCO API", version="0.2.0")
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

class DeployPayload(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    project: str = os.getenv("DEFAULT_GCP_PROJECT", "hrz-geo-dig-res-endor-1")
    region: str = os.getenv("DEFAULT_GCP_REGION", "me-west1")
    stack: str = "dev"

class SynthPayload(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    project: str = os.getenv("DEFAULT_GCP_PROJECT", "hrz-geo-dig-res-endor-1")
    region: str = os.getenv("DEFAULT_GCP_REGION", "me-west1")

class EdgeValidation(BaseModel):
    source_type: str
    target_type: str

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/node-types")
def get_node_types():
    return [cls.ui_schema() for cls in NODE_REGISTRY.values()]


@app.post("/api/validate-edge")
def validate_edge(body: EdgeValidation):
    valid = body.source_type == body.target_type
    return {"valid": valid, "reason": None if valid else f"Cannot connect {body.source_type} → {body.target_type}"}


@app.get("/api/state")
def get_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            data = yaml.safe_load(f) or {}
            return {"nodes": data.get("nodes", []), "edges": data.get("edges", [])}
    return {"nodes": [], "edges": []}


@app.post("/api/graph")
async def save_graph(payload: GraphPayload):
    # Read deployed status directly from Pulumi state
    actual       = read_actual_state(str(STACK_DIR))
    actual_ids   = set(actual.get("node_ids", []))
    actual_nodes = actual.get("nodes", {})

    nodes_with_status = []
    for n in payload.nodes:
        n_copy   = dict(n)
        node_info = actual_nodes.get(n["id"], {})
        n_copy["deployed"] = n["id"] in actual_ids
        n_copy["status"]   = node_info.get("status", "unknown") if n["id"] in actual_ids else "pending"
        nodes_with_status.append(n_copy)

    state = {"nodes": nodes_with_status, "edges": payload.edges}
    with open(STATE_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    await manager.broadcast({"event": "graph_saved", "node_count": len(payload.nodes)})
    return {"status": "saved"}


# ── NEW: Synth preview (no deploy) ────────────────────────────────────────────

@app.post("/api/synth")
async def synth_preview(payload: SynthPayload):
    """
    Returns the generated CDKTF Python code + resolved graph without deploying.
    Useful to inspect what will be deployed before clicking Deploy.
    """
    result = await synthesize_only(
        nodes=payload.nodes,
        edges=payload.edges,
        project=payload.project,
        region=payload.region,
    )
    return result


# ── NEW: Real CDKTF deploy ────────────────────────────────────────────────────

@app.post("/api/deploy")
async def deploy(payload: DeployPayload):
    """
    Generates a CDKTF stack from the graph and runs `cdktf deploy --auto-approve`.
    Progress is streamed over WebSocket. HTTP response returns after completion.

    Required fields in payload:
        project (str): GCP project ID
        region  (str): GCP region (default us-central1)

    Authentication:
        The server process must have GCP credentials available:
        - GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service-account JSON, OR
        - gcloud auth application-default login already run
    """
    await manager.broadcast({
        "event": "deploy_started",
        "total": len(payload.nodes),
        "create": len(payload.nodes),
        "update": 0,
        "destroy": 0,
        "touched_ids": [n["id"] for n in payload.nodes],
    })

    # The DAG runner will emit __node_working__ / __node_deployed__ / __node_failed__
    # signals per node as it progresses — no pre-broadcast needed here.

    async def ws_log(msg: str, level: str = "info", node_id: str | None = None):
        # Internal DAG signals → translate to typed UI events
        if msg == "__node_working__":
            await manager.broadcast({"event": "node_working", "node_id": node_id})
            return
        if msg == "__node_deployed__":
            await manager.broadcast({
                "event": "node_status", "node_id": node_id,
                "status": "deployed", "action": "create",
            })
            return
        if msg == "__node_failed__":
            await manager.broadcast({
                "event": "node_status", "node_id": node_id, "status": "failed",
            })
            return
        # Normal log line — include node_id so UI can route it to the right panel
        await manager.broadcast({
            "event": "log", "msg": msg, "level": level,
            **({"node_id": node_id} if node_id else {}),
        })

    result = await synthesize_and_deploy(
        nodes=payload.nodes,
        edges=payload.edges,
        project=payload.project,
        region=payload.region,
        stack=payload.stack,
        log=ws_log,
        work_dir=str(STACK_DIR),
    )

    if result["status"] in ("ok", "partial"):
        outputs = result.get("outputs", {})

        # ── Broadcast outputs (e.g. CR URLs) ─────────────────────────────
        # No actual.yaml — Pulumi state IS the source of truth
        if outputs:
            await manager.broadcast({
                "event":   "deploy_outputs",
                "outputs": outputs,
            })

        await manager.broadcast({"event": "deploy_complete", "changed": len(payload.nodes)})
        return {"status": "ok", "outputs": outputs}

    else:
        # Mark all nodes failed
        for node in payload.nodes:
            await manager.broadcast({
                "event":   "node_status",
                "node_id": node["id"],
                "status":  "failed",
            })
        await manager.broadcast({"event": "deploy_complete", "changed": 0})
        return JSONResponse(
            status_code=500,
            content={"status": "error", "phase": result.get("phase"), "detail": result.get("output", "")},
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

@app.get("/api/actual-state")
def get_actual_state():
    """Return the real deployed state read directly from Pulumi stacks."""
    return read_actual_state(str(STACK_DIR))


@app.get("/api/logs/{node_id}")
async def stream_logs(node_id: str):
    async def generate():
        while True:
            yield f"data: [INFO] {node_id}: heartbeat at {datetime.datetime.now()}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)