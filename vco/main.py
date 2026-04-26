"""
main.py
=======
Visual Cloud Orchestrator — FastAPI entry point.

Run:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import deploy, graph, nodes, realtime, logs, namespaces, terraform


logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Visual Cloud Orchestrator",
    version="0.4.0",
    description=(
        "Drag-and-drop GCP infrastructure builder powered by Pulumi Automation API. "
        "All deploy progress is streamed in real time over WebSocket. "
        "Multi-namespace support: each namespace has fully isolated state, stacks and logs."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nodes.router)
app.include_router(graph.router)
app.include_router(deploy.router)
app.include_router(realtime.router)
app.include_router(logs.router)
app.include_router(namespaces.router)  
app.include_router(terraform.router)

logger.info("VCO API ready — %d routes registered", len(app.routes))