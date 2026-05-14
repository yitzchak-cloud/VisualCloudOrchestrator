"""
nodes/resource/artifact_registry/_pulumi.py
===========================================
Pulumi program factory for ArtifactRegistryNode.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import _resource_name

if TYPE_CHECKING:
    from nodes.resource.artifact_registry.artifact_registry import ArtifactRegistryNode

logger = logging.getLogger(__name__)

def make_pulumi_program(
    node:             "ArtifactRegistryNode",
    ctx:              dict[str, Any],
    project:          str,
    region:           str,
    all_nodes:        list[dict],
    deployed_outputs: dict[str, dict],
) -> Callable[[], None]:
    
    node_dict = ctx.get("node", {})
    props     = node_dict.get("props", {})

    name       = props.get("name") or _resource_name(node_dict)
    format_val = props.get("format", "DOCKER")
    desc       = props.get("description", "")
    repo_loc   = props.get("region", region) # Default to orchestrator region if not specified

    def program() -> None:
        # ── Create the GCP resource ───────────────────────────────────────────
        repo = gcp.artifactregistry.Repository(
            name,
            repository_id=name,
            location=repo_loc,
            project=project,
            format=format_val,
            description=desc if desc else None,
            opts=pulumi.ResourceOptions(delete_before_replace=True),
        )
        image_prefix = repo.location.apply(
            lambda loc: f"{loc}-docker.pkg.dev/{project}/{name}"
        )

        # ── Export outputs ────────────────────────────────────────────────────
        pulumi.export("name", repo.name)
        pulumi.export("id",   repo.id)
        pulumi.export("image_prefix",  image_prefix)
        pulumi.export("name",          repo.name)

    return program