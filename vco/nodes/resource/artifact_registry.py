"""
nodes/artifact_registry.py — Artifact Registry repository node (fully self-describing).

Purpose
-------
Creates a Docker (or other format) repository in Google Artifact Registry.
The image path prefix is exported so downstream CloudRunNode / CloudFunctionsNode
can reference it without hardcoding.

Equivalent gcloud
-----------------
  gcloud artifacts repositories create ${REPO_NAME} \\
    --location=${REPO_REGION} \\
    --repository-format=docker

Topology
--------
  ArtifactRegistryNode ──(STORAGE)──► CloudRunNode        (image source reference)
  ArtifactRegistryNode ──(STORAGE)──► CloudFunctionsNode  (image source reference)

Exports
-------
  repository_id  — short repository id
  location       — repository location
  image_prefix   — full image path prefix, e.g.:
                   me-west1-docker.pkg.dev/my-project/my-repo
  name           — full resource name
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class ArtifactRegistryNode(GCPNode):
    """
    Artifact Registry — Docker/package repository.

    Connect to CloudRunNode or CloudFunctionsNode → exports the image prefix
    (e.g. me-west1-docker.pkg.dev/project/repo) as ARTIFACT_REGISTRY_<NAME>
    env var into the consumer node.

    Equivalent gcloud:
      gcloud artifacts repositories create ${REPO_NAME} \\
        --location=${REPO_REGION} \\
        --repository-format=docker
    """

    params_schema: ClassVar = [
        {
            "key":         "name",
            "label":       "Repository Name",
            "type":        "text",
            "default":     "",
            "placeholder": "my-docker-repo",
        },
        {
            "key":     "location",
            "label":   "Location",
            "type":    "select",
            "options": ["me-west1", "us-central1", "us-east1", "europe-west1", "asia-east1"],
            "default": "me-west1",
        },
        {
            "key":     "format",
            "label":   "Repository Format",
            "type":    "select",
            "options": ["DOCKER", "MAVEN", "NPM", "PYTHON", "APT", "YUM", "HELM"],
            "default": "DOCKER",
        },
        {
            "key":         "description",
            "label":       "Description",
            "type":        "text",
            "default":     "",
            "placeholder": "Docker images for my services",
        },
    ]

    inputs:  ClassVar = []
    outputs: ClassVar = [
        Port("images", PortType.STORAGE, multi=True),  # → CloudRunNode / CloudFunctionsNode
    ]

    node_color:  ClassVar = "#818cf8"
    icon:        ClassVar = "artifactRegistry"
    category:    ClassVar = "Storage"
    description: ClassVar = "Artifact Registry — Docker/package repository"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id:
            if tgt_type in ("CloudRunNode", "CloudFunctionsNode"):
                # Inject the image prefix as env var into the consumer
                ctx[tgt_id].setdefault("artifact_registry_ids", []).append(self.node_id)
                return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(
        self,
        ctx:              dict,
        project:          str,
        region:           str,
        all_nodes:        list,
        deployed_outputs: dict,
    ) -> Callable[[], None] | None:

        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        def program() -> None:
            repo_name   = props.get("name") or _resource_name(node_dict)
            location    = props.get("location", region)
            fmt         = props.get("format", "DOCKER")
            description = props.get("description", "")

            repo = gcp.artifactregistry.Repository(
                self.node_id,
                repository_id=repo_name,
                location=location,
                format=fmt,
                description=description,
                project=project,
            )

            # Full image path prefix for docker:
            #   {location}-docker.pkg.dev/{project}/{repo_name}
            image_prefix = repo.location.apply(
                lambda loc: f"{loc}-docker.pkg.dev/{project}/{repo_name}"
            )

            pulumi.export("repository_id", repo.repository_id)
            pulumi.export("location",      repo.location)
            pulumi.export("image_prefix",  image_prefix)
            pulumi.export("name",          repo.name)

        return program

    # ------------------------------------------------------------------
    # Post-deploy
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "image_prefix": pulumi_outputs.get("image_prefix", ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return None
