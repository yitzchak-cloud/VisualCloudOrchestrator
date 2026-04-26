"""
api/routes/graph.py
===================
/api/state   — read last saved graph   (query param: ?namespace=default)
/api/graph   — save graph              (body field: namespace)
"""
from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter

from api.models import GraphPayload
from core.state import stack_dir as _stack_dir, state_file as _state_file
from core.ws_manager import manager
from pulumi_synth import read_actual_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/state")
def get_state(namespace: str = "default"):
    """Return the last-saved desired graph for the given namespace."""
    sf = _state_file(namespace)
    if sf.exists():
        with open(sf) as f:
            data = yaml.safe_load(f) or {}
        logger.info(
            "Loaded state for namespace=%s from %s  (nodes=%d)",
            namespace, sf, len(data.get("nodes", [])),
        )
        return {"nodes": data.get("nodes", []), "edges": data.get("edges", [])}

    logger.info("No state file for namespace=%s — returning empty graph", namespace)
    return {"nodes": [], "edges": []}


@router.post("/graph")
async def save_graph(payload: GraphPayload):
    """
    Persist the canvas to YAML for the given namespace, annotating each
    node with its live deployed status read from Pulumi stacks.
    """
    ns = payload.namespace
    sf = _state_file(ns)
    sd = _stack_dir(ns)
    logger.info(
        "Saving graph: namespace=%s  nodes=%d  edges=%d",
        ns, len(payload.nodes), len(payload.edges),
    )

    actual       = read_actual_state(str(sd))
    actual_ids   = set(actual.get("node_ids", []))
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

    state = {"nodes": nodes_with_status, "edges": payload.edges}
    with open(sf, "w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True)

    logger.info("Graph saved to %s", sf)
    await manager.broadcast_graph_saved(len(payload.nodes))
    return {"status": "saved", "node_count": len(payload.nodes), "namespace": ns}


@router.get("/actual-state")
def get_actual_state(namespace: str = "default"):
    """Return the real deployed state read directly from Pulumi stacks."""
    sd    = _stack_dir(namespace)
    state = read_actual_state(str(sd))
    logger.info(
        "Actual state namespace=%s: %d deployed nodes",
        namespace, len(state.get("node_ids", [])),
    )
    return state