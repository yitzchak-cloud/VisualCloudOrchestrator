"""
nodes/resource/artifact_registry/artifact_registry.py
=====================================================
ArtifactRegistryNode — Manages a Google Cloud Artifact Registry repository.

Topology
--------
  <SourceNode> ──(IAM_BINDING)──► ArtifactRegistryNode

Exports (Pulumi outputs)
------------------------
  name  — resource name
  id    — resource ID
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

# Import Pulumi + Terraform delegates
from nodes.resource.artifact_registry._pulumi import make_pulumi_program
from nodes.resource.artifact_registry._terraform import (
    make_terraform_call_vars,
    terraform_instance_prefix as _tf_prefix,
)

logger = logging.getLogger(__name__)

class K:
    pass # Add context keys here if specific edge resolution dependencies are added later

@dataclass
class ArtifactRegistryNode(GCPNode):
    """
    Manages a GCP Artifact Registry repository.
    
    Connect IAM bindings to this node to manage repository permissions.
    """

    inputs: ClassVar = [
        Port("iam_binding", PortType.IAM_BINDING, required=False, multi_in=True),
    ]
    outputs: ClassVar = [
        # Port("repository", PortType.ANY, multi=True), # Generic output for resources that might consume this repo
    ]

    node_color:  ClassVar = "#8b5cf6"                    
    icon:        ClassVar = "inventory_2"                 
    category:    ClassVar = "CI/CD"                  
    description: ClassVar = "Google Cloud Artifact Registry repository"

    # ── Edge wiring ──────────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        """
        No special complex edge resolution needed for basic Artifact Registry.
        IAM bindings are handled natively by the IamBindingNode targeting this node's type.
        """
        return False

    # ── DAG dependencies ─────────────────────────────────────────────────────────

    def dag_deps(self, ctx) -> list[str]:
        return []

    # ── Pulumi program ──────────────────────────────────────────────────────────

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        self._props = ctx.get("node", {}).get("props", {})
        return make_pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs)

    # ── Terraform ───────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return _tf_prefix()

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        self._props = ctx.get("node", {}).get("props", {})
        return make_terraform_call_vars(self, ctx, project, region, all_nodes)

    # ── Live outputs + logging ──────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "name": pulumi_outputs.get("name", ""),
            "id":   pulumi_outputs.get("id",   ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        # Artifact Registry logs are typically audit logs, standard SSE stream omitted for simplicity
        return None