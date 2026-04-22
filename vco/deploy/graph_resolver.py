"""
deploy/graph_resolver.py
========================
Generic graph resolution and DAG builder.

Both functions are now **completely resource-agnostic**.
All edge-handling and dependency logic lives inside each node class
(via resolve_edges / dag_deps).  Adding a new resource type
requires ZERO changes here.

  resolve_graph(nodes, edges, node_registry) → ctx
      Calls node.resolve_edges() for every (node, edge) pair.
      Returns a per-node context dict populated by the nodes themselves.

  build_dag(nodes, ctx, node_registry) → list[node_id]
      Topological sort (Kahn's algorithm).
      Calls node.dag_deps(ctx) to learn each node's dependencies.
      Raises ValueError on cycles.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _instantiate(node_dict: dict, node_registry: dict) -> Any | None:
    """
    Create a lightweight GCPNode instance from a raw node dict.
    Returns None if the type is not registered (unknown / UI-only node).
    """
    cls = node_registry.get(node_dict.get("type", ""))
    if cls is None:
        return None
    return cls(node_id=node_dict["id"], label=node_dict.get("label", ""))


# ── 1. Graph resolver ─────────────────────────────────────────────────────────

def resolve_graph(
    nodes:         list[dict],
    edges:         list[dict],
    node_registry: dict,
) -> dict[str, Any]:
    """
    Walk every edge and let each node annotate the context dict.

    ctx layout:
        ctx[node_id]["node"]   → the raw node dict
        ctx[node_id][*]        → keys added by node.resolve_edges()
                                 (e.g. "topic_id", "publishes_to_topics", …)
    """
    by_id: dict[str, dict] = {n["id"]: n for n in nodes}
    ctx:   dict[str, dict] = {n["id"]: {"node": n} for n in nodes}

    # Pre-instantiate all nodes once
    instances: dict[str, Any] = {}
    for n in nodes:
        inst = _instantiate(n, node_registry)
        if inst is not None:
            instances[n["id"]] = inst

    for edge in edges:
        src      = edge["source"]
        tgt      = edge["target"]
        src_type = by_id.get(src, {}).get("type", "")
        tgt_type = by_id.get(tgt, {}).get("type", "")

        handled = False
        # Give every registered node a chance to claim this edge
        for node_id, inst in instances.items():
            if inst.resolve_edges(src, tgt, src_type, tgt_type, ctx):
                handled = True
                # Don't break — multiple nodes may need to react to the same edge
                # (e.g. both the source and target update their own ctx keys).
                # resolve_edges must be idempotent if called for an unrelated edge.

        if not handled:
            logger.debug(
                "Edge ignored (no handler): %s (%s) → %s (%s)",
                src, src_type, tgt, tgt_type,
            )

    logger.info("resolve_graph: %d nodes, %d edges processed", len(nodes), len(edges))
    return ctx


# ── 2. DAG builder ────────────────────────────────────────────────────────────

def build_dag(
    nodes:         list[dict],
    ctx:           dict[str, Any],
    node_registry: dict,
) -> list[str]:
    """
    Topological sort of nodes by deployment dependency.
    Returns a list of node IDs in safe deployment order.
    Raises ValueError if a cycle is detected.
    """
    deps: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    for n in nodes:
        nid  = n["id"]
        inst = node_registry.get(n.get("type", ""))
        if inst is None:
            continue   # unknown type — no deps, deploy last
        # Instantiate just to call dag_deps (cheap — no I/O)
        node_obj = inst(node_id=nid, label=n.get("label", ""))
        deps[nid] = node_obj.dag_deps(ctx.get(nid, {}))

    # Kahn's algorithm
    in_degree = {n["id"]: len(deps[n["id"]]) for n in nodes}
    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order: list[str]  = []

    rdeps: dict[str, list[str]] = defaultdict(list)
    for nid, d_list in deps.items():
        for dep in d_list:
            rdeps[dep].append(nid)

    while queue:
        nid = queue.popleft()
        order.append(nid)
        for dependent in rdeps[nid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(nodes):
        cycle_nodes = [n["id"] for n in nodes if n["id"] not in set(order)]
        raise ValueError(f"Cycle detected in graph involving: {cycle_nodes}")

    logger.info("build_dag: deployment order → %s", order)
    return order