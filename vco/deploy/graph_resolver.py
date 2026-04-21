"""
deploy/graph_resolver.py
========================
Two pure functions — no Pulumi, no I/O, no side effects:

  resolve_graph(nodes, edges) → ctx
      Annotates each node with its relationships (topics it publishes to,
      subscriptions that feed it, etc.).

  build_dag(nodes, ctx) → list[node_id]
      Topological sort (Kahn's algorithm).
      Raises ValueError on cycles.

Dependency rules (what must exist BEFORE deploying X):
  PubsubTopicNode          → nothing
  CloudRunNode             → PubsubTopics it publishes to   (needs topic name as env var)
  PubsubPullSubscription   → its parent PubsubTopic
  PubsubPushSubscription   → its parent PubsubTopic
                           + the CloudRun whose URI it pushes to  (needs live URI)
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger(__name__)


# ── Edge type constants ────────────────────────────────────────────────────────

_CR   = "CloudRunNode"
_TOP  = "PubsubTopicNode"
_PULL = "PubsubPullSubscriptionNode"
_PUSH = "PubsubPushSubscriptionNode"


# ── 1. Graph resolver ─────────────────────────────────────────────────────────

def resolve_graph(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """
    Walk every edge and populate a per-node context dict with relationship keys:

      publishes_to_topics  : list[node_id]  (CR → Topic)
      publisher_cr_ids     : list[node_id]  (Topic ← CR)
      topic_id             : node_id        (Subscription → Topic)
      consumer_cr_ids      : list[node_id]  (PullSub → CR)
      receives_from_subs   : list[node_id]  (CR ← Sub)
      push_target_cr_ids   : list[node_id]  (PushSub → CR)
    """
    by_id: dict[str, dict] = {n["id"]: n for n in nodes}
    ctx:   dict[str, dict] = {n["id"]: {"node": n} for n in nodes}

    for edge in edges:
        src      = edge["source"]
        tgt      = edge["target"]
        src_type = by_id.get(src, {}).get("type", "")
        tgt_type = by_id.get(tgt, {}).get("type", "")

        if src_type == _CR and tgt_type == _TOP:
            # CR publishes to Topic
            ctx[src].setdefault("publishes_to_topics", []).append(tgt)
            ctx[tgt].setdefault("publisher_cr_ids",    []).append(src)
            logger.debug("Edge: %s (CR) → %s (Topic)", src, tgt)

        elif src_type == _TOP and tgt_type in (_PULL, _PUSH):
            # Topic owns Subscription
            ctx[tgt]["topic_id"] = src
            logger.debug("Edge: %s (Topic) → %s (Subscription)", src, tgt)

        elif src_type == _PULL and tgt_type == _CR:
            # PullSub feeds CR
            ctx[src].setdefault("consumer_cr_ids",    []).append(tgt)
            ctx[tgt].setdefault("receives_from_subs", []).append(src)
            logger.debug("Edge: %s (PullSub) → %s (CR)", src, tgt)

        elif src_type == _PUSH and tgt_type == _CR:
            # PushSub pushes to CR endpoint
            ctx[src].setdefault("push_target_cr_ids", []).append(tgt)
            ctx[tgt].setdefault("receives_from_subs", []).append(src)
            logger.debug("Edge: %s (PushSub) → %s (CR)", src, tgt)

        else:
            logger.debug("Edge ignored (no rule): %s (%s) → %s (%s)", src, src_type, tgt, tgt_type)

    logger.info("resolve_graph: %d nodes, %d edges processed", len(nodes), len(edges))
    return ctx


# ── 2. DAG builder ────────────────────────────────────────────────────────────

def build_dag(nodes: list[dict], ctx: dict[str, Any]) -> list[str]:
    """
    Topological sort of nodes by deployment dependency.
    Returns a list of node IDs in safe deployment order.
    Raises ValueError if a cycle is detected.
    """
    deps: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    for node in nodes:
        nid   = node["id"]
        ntype = node.get("type", "")
        nc    = ctx.get(nid, {})

        if ntype == _CR:
            deps[nid].extend(nc.get("publishes_to_topics", []))

        elif ntype in (_PULL, _PUSH):
            if nc.get("topic_id"):
                deps[nid].append(nc["topic_id"])

        if ntype == _PUSH:
            deps[nid].extend(nc.get("push_target_cr_ids", []))

    # Kahn's algorithm
    in_degree = {n["id"]: len(deps[n["id"]]) for n in nodes}
    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order: list[str] = []

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
