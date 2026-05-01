"""
nodes/cloud_vision.py — Cloud Vision API node (fully self-describing).

Purpose
-------
Represents a call to the Cloud Vision API from an orchestrating node
(WorkflowNode or CloudRunNode).

The Cloud Vision API is a *managed* Google API — there is no Pulumi resource
to create.  This node is therefore a **reference / visual node**:
  - It records that the Vision API is used in the architecture.
  - It injects an API_URL_CLOUD_VISION env var into any connected CloudRunNode.
  - It generates a `CLOUD_VISION_ENDPOINT` label export so WorkflowNode YAML
    can reference it.
  - It enables the Vision API via a `gcp.projects.Service` resource (optional,
    controlled by `enable_api` prop).

Topology
--------
  WorkflowNode   ──(HTTP_TARGET)──► CloudVisionNode   (visual step reference)
  CloudRunNode   calls Vision API via env var          (no direct edge needed)

  IamBindingNode ──(IAM_BINDING)──► CloudVisionNode   (grant SA Vision user role)

Equivalent gcloud setup
-----------------------
  gcloud services enable vision.googleapis.com

  # The SA running the Workflow or CR needs:
  #   roles/serviceusage.serviceUsageConsumer  (project level, usually inherited)
  # No per-resource IAM binding needed for the Vision API.

Exports
-------
  endpoint   — the Vision API endpoint URL
  api_name   — "vision.googleapis.com"

Env var injected into CloudRunNode / WorkflowNode (via HTTP_TARGET wire):
  API_URL_CLOUD_VISION  — https://vision.googleapis.com/v1
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

_VISION_ENDPOINT = "https://vision.googleapis.com/v1"
_VISION_API      = "vision.googleapis.com"


@dataclass
class CloudVisionNode(GCPNode):
    """
    Cloud Vision API — image analysis (labels, safe-search, text, faces, objects).

    Connect FROM WorkflowNode or CloudRunNode to represent a Vision API call step.
    The node optionally enables the Vision API in the project.

    No GCP resource is created for the API call itself — Vision is a managed
    service called via HTTPS.  The node exports the endpoint URL and (optionally)
    enables the API.
    """

    params_schema: ClassVar = [
        {
            "key":     "enable_api",
            "label":   "Enable Vision API in project",
            "type": "select",
            "options": ["true", "false"],
            "default": True,
        },
        {
            "key":         "custom_endpoint",
            "label":       "Custom Endpoint (leave blank for default)",
            "type":        "text",
            "default":     "",
            "placeholder": "https://vision.googleapis.com/v1",
        },
    ]

    inputs: ClassVar = [
        Port("callers",         PortType.HTTP_TARGET, required=False, multi=True, multi_in=True),
        Port("iam_binding",     PortType.IAM_BINDING, required=False, multi=True, multi_in=True),
        Port("visual",          PortType.VISUAL_CONNECTION, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("api_target",      PortType.HTTP_TARGET, multi=True),
    ]

    node_color:  ClassVar = "#0ea5e9"
    icon:        ClassVar = "cloudVision"
    category:    ClassVar = "AI_and_ML"
    description: ClassVar = "Cloud Vision API — image labeling, safe-search, OCR"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # WorkflowNode / CloudRunNode → CloudVisionNode
        # Tell the caller about this Vision node so it can inject the env var.
        if tgt_id == self.node_id:
            if src_type in ("WorkflowNode", "CloudRunNode"):
                ctx[src_id].setdefault("visual_api_ids", []).append(self.node_id)
                return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(
        self,
        ctx:              dict[str, Any],
        project:          str,
        region:           str,
        all_nodes:        list[dict],
        deployed_outputs: dict[str, dict],
    ) -> Callable[[], None] | None:

        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        enable_api       = props.get("enable_api", True)
        custom_endpoint  = props.get("custom_endpoint", "").strip()
        endpoint         = custom_endpoint or _VISION_ENDPOINT

        def program() -> None:
            # Optionally enable the API in the project.
            # Equivalent: gcloud services enable vision.googleapis.com
            if enable_api:
                gcp.projects.Service(
                    f"{self.node_id}-enable",
                    project=project,
                    service=_VISION_API,
                    disable_dependent_services=False,
                    disable_on_destroy=False,
                )

            pulumi.export("endpoint", endpoint)
            pulumi.export("url",      endpoint)   # alias — callers read "url"
            pulumi.export("name",     "cloud-vision")
            pulumi.export("api_name", _VISION_API)

        return program

    # ------------------------------------------------------------------
    # Post-deploy
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"endpoint": pulumi_outputs.get("endpoint", _VISION_ENDPOINT)}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        # Vision API calls appear in Cloud Audit Logs under the project
        return LogSource(
            filter=(
                'protoPayload.serviceName="vision.googleapis.com"'
            ),
            project=project,
            page_size=50,
        )