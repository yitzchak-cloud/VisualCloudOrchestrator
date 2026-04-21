"""
main.py
=======
Visual Cloud Orchestrator — FastAPI entry point.

Run:
    uvicorn main:app --reload --port 8000

Project layout:
    main.py                  ← you are here (app factory + startup logging)
    api/
        models.py            ← Pydantic request/response schemas
        routes/
            nodes.py         ← GET  /api/node-types
                                POST /api/validate-edge
            graph.py         ← GET  /api/state
                                POST /api/graph
                                GET  /api/actual-state
            deploy.py        ← POST /api/synth
                                POST /api/deploy
            realtime.py      ← GET  /api/logs/{node_id}  (SSE)
                                WS   /ws
    core/
        registry.py          ← discovers & registers all GCPNode subclasses
        state.py             ← shared path constants (STATE_FILE, STACK_DIR)
        ws_manager.py        ← WebSocket connection pool + typed broadcast helpers
        log_bridge.py        ← translates deploy-engine signals → WS events
    pulumi_synth.py          ← DAG builder + Pulumi Automation API orchestrator
"""
from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import deploy, graph, nodes, realtime

# ── Logging setup ─────────────────────────────────────────────────────────────
# One-liner config: DEBUG to stdout during development.
# In production, replace with a JSON formatter and ship to Cloud Logging.

logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Visual Cloud Orchestrator",
    version="0.3.0",
    description=(
        "Drag-and-drop GCP infrastructure builder powered by Pulumi Automation API. "
        "All deploy progress is streamed in real time over WebSocket."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(nodes.router)
app.include_router(graph.router)
app.include_router(deploy.router)
app.include_router(realtime.router)

logger.info("VCO API ready — %d routes registered", len(app.routes))
