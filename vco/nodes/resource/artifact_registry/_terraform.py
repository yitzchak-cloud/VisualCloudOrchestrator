"""
nodes/resource/artifact_registry/_terraform.py
==============================================
Terraform call-vars factory for ArtifactRegistryNode.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from nodes.base_node import _tf_name

if TYPE_CHECKING:
    from nodes.resource.artifact_registry.artifact_registry import ArtifactRegistryNode

logger = logging.getLogger(__name__)

def terraform_instance_prefix(mode: str = "default") -> str:
    return "ar_repo"

def make_terraform_call_vars(
    node:      "ArtifactRegistryNode",
    ctx:       dict[str, Any],
    project:   str,
    region:    str,
    all_nodes: list[dict],
) -> dict[str, str]:
    
    node_dict = ctx.get("node", {})
    props     = node_dict.get("props", {})

    name = props.get("name") or _tf_name(node_dict)
    repo_loc = props.get("region", region)

    if not name:
        logger.warning("Terraform: %s missing name — skipped", node.node_id)
        return {}

    return {
        "repository_id": f'"{name}"',
        "location":      f'"{repo_loc}"',
        "format":        f'"{props.get("format", "DOCKER")}"',
        "description":   f'"{props.get("description", "")}"',
    }