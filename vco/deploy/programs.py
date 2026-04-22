"""
deploy/programs.py
==================
Generic Pulumi program dispatcher.

Previously this file contained one factory function per resource type.
Now it contains a single  build_program()  call that delegates entirely
to  node.pulumi_program().

Adding a new resource type requires ZERO changes here.
All Pulumi logic lives inside the node class definition.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def build_program(
    node:             dict,
    ntype:            str,
    nc:               dict,
    project:          str,
    region:           str,
    all_nodes:        list[dict],
    deployed_outputs: dict[str, dict],
    node_registry:    dict,
) -> Callable[[], None] | None:
    """
    Look up the node class in *node_registry*, instantiate it, and
    delegate to  node.pulumi_program().

    Returns None if:
      - the node type is not registered (unknown / UI-only)
      - the node itself returns None (missing upstream dependency)

    Callers should treat None as "skip this node".
    """
    cls = node_registry.get(ntype)
    if cls is None:
        logger.warning("build_program: unknown node type '%s' — skipping", ntype)
        return None

    node_obj = cls(node_id=node["id"], label=node.get("label", ""))
    program  = node_obj.pulumi_program(nc, project, region, all_nodes, deployed_outputs)

    if program is None:
        logger.warning(
            "build_program: %s (%s) returned None — skipping (missing dependency?)",
            node.get("label", node["id"]), ntype,
        )
    return program