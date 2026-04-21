"""
api/routes/graph.py
===================
/api/state   — read last saved graph
/api/graph   — save graph (overlay with Pulumi actual state)
"""
from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter

from api.models import GraphPayload
from core.state import STATE_FILE, STACK_DIR
from core.ws_manager import manager
from pulumi_synth import read_actual_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/state")
def get_state():
    """Return the last-saved desired graph (nodes + edges)."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            data = yaml.safe_load(f) or {}
        logger.info("Loaded state from %s  (nodes=%d)", STATE_FILE, len(data.get("nodes", [])))
        return {"nodes": data.get("nodes", []), "edges": data.get("edges", [])}

    logger.info("No state file found at %s — returning empty graph", STATE_FILE)
    return {"nodes": [], "edges": []}


@router.post("/graph")
async def save_graph(payload: GraphPayload):
    """
    Persist the canvas to YAML, annotating each node with its live
    deployed status read straight from Pulumi stacks.
    """
    logger.info("Saving graph: %d nodes, %d edges", len(payload.nodes), len(payload.edges))

    actual      = read_actual_state(str(STACK_DIR))
    actual_ids  = set(actual.get("node_ids", []))
    actual_nodes = actual.get("nodes", {})

    nodes_with_status = []
    for n in payload.nodes:
        n_copy    = dict(n)
        node_info = actual_nodes.get(n["id"], {})
        deployed  = n["id"] in actual_ids
        status    = node_info.get("status", "unknown") if deployed else "pending"

        n_copy["deployed"] = deployed
        n_copy["status"]   = status
        nodes_with_status.append(n_copy)
        logger.debug("  node %s → deployed=%s  status=%s", n["id"], deployed, status)

    state = {"nodes": nodes_with_status, "edges": payload.edges}
    with open(STATE_FILE, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    logger.info("Graph saved to %s", STATE_FILE)
    await manager.broadcast_graph_saved(len(payload.nodes))
    return {"status": "saved", "node_count": len(payload.nodes)}


@router.get("/actual-state")
def get_actual_state():
    """Return the real deployed state read directly from Pulumi stacks."""
    state = read_actual_state(str(STACK_DIR))
    logger.info(
        "Actual state: %d deployed nodes",
        len(state.get("node_ids", [])),
    )
    return state
