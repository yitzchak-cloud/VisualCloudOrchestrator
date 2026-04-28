"""
nodes/visual_nodes.py — Visual-only / stub nodes for architecture diagramming.

These nodes appear on the canvas for documentation and architecture clarity,
but do NOT create any GCP resources when deployed.  They are useful for:

  • Representing external APIs (Cloud Vision, Maps, etc.) that are called
    via HTTP by Cloud Run — no Pulumi resource needed, just env-var wiring.
  • Representing Cloud Functions (Gen 1/2) before a dedicated node is built.
  • Any GCP service that is consumed but not managed by this orchestrator.

All visual nodes:
  - Export a url and name for env-var injection into connected Cloud Run nodes.
  - Accept a ServiceAccountNode for documentation purposes (no IAM created here).
  - Are marked with  visual_only = True  so the engine can skip the deploy step.

Topology
--------
  CloudVisionNode     ──(HTTP_TARGET)──► CloudRunNode  (injects CLOUD_VISION_URL)
  CloudFunctionsNode  ──(HTTP_TARGET)──► CloudRunNode  (injects CLOUD_FUNCTIONS_URL_<NAME>)
  ExternalApiNode     ──(HTTP_TARGET)──► CloudRunNode  (injects EXTERNAL_API_URL_<NAME>)

WorkflowNode ──► CloudVisionNode     (visual only — shows workflow calls Vision)
WorkflowNode ──► CloudFunctionsNode  (visual only — shows workflow calls Function)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi

from nodes.base_node import GCPNode, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


# ── Cloud Vision (visual-only) ────────────────────────────────────────────────

@dataclass
class CloudVisionNode(GCPNode):
    """
    Cloud Vision API — visual-only stub.

    No resource is created.  Connect to WorkflowNode or CloudRunNode to
    document that the service calls Vision API.  The Vision API endpoint
    is injected as CLOUD_VISION_URL into connected callers.
    """

    params_schema: ClassVar = [
        {
            "key": "name",
            "label": "Display Name",
            "type": "text",
            "default": "Cloud Vision",
            "placeholder": "Cloud Vision",
        },
        {
            "key": "api_url",
            "label": "API Endpoint URL",
            "type": "text",
            "default": "https://vision.googleapis.com/v1",
            "placeholder": "https://vision.googleapis.com/v1",
        },
        {
            "key": "features",
            "label": "Features (comma-separated, for docs)",
            "type": "text",
            "default": "LABEL_DETECTION,SAFE_SEARCH_DETECTION",
            "placeholder": "LABEL_DETECTION,SAFE_SEARCH_DETECTION",
        },
    ]

    inputs:  ClassVar = []
    outputs: ClassVar = [
        Port("callers", PortType.HTTP_TARGET, multi=True),
    ]

    node_color:  ClassVar = "#06b6d4"
    icon:        ClassVar = "cloudVision"
    category:    ClassVar = "AI_ML"
    description: ClassVar = "Cloud Vision API (visual reference — no resource created)"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # CloudVisionNode → CloudRunNode: inject URL env var
        if src_id == self.node_id and tgt_type in ("CloudRunNode", "WorkflowNode"):
            ctx[tgt_id].setdefault("visual_api_ids", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        def program() -> None:
            api_url = props.get("api_url", "https://vision.googleapis.com/v1")
            name    = props.get("name", "Cloud Vision")
            pulumi.export("url",  api_url)
            pulumi.export("name", re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-"))

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "url":  pulumi_outputs.get("url",  ""),
            "name": pulumi_outputs.get("name", ""),
        }

    def log_source(self, pulumi_outputs, project, region):
        return None


# ── Cloud Functions (visual-only / stub) ──────────────────────────────────────

@dataclass
class CloudFunctionsNode(GCPNode):
    """
    Cloud Functions — visual stub node.

    Use this to document that a Cloud Function exists and is called
    by a Cloud Run service or Workflow.  The function URL is injected
    as CLOUD_FUNCTIONS_URL_<NAME> into connected callers.

    For full Cloud Functions deployment, a dedicated node with Pulumi
    gcp.cloudfunctionsv2.Function support should be built separately.
    This stub covers the architecture diagram use-case.
    """

    params_schema: ClassVar = [
        {
            "key": "name",
            "label": "Function Name",
            "type": "text",
            "default": "",
            "placeholder": "extract-metadata",
        },
        {
            "key": "function_url",
            "label": "Function URL (if already deployed)",
            "type": "text",
            "default": "",
            "placeholder": "https://REGION-PROJECT.cloudfunctions.net/FUNC",
        },
        {
            "key": "runtime",
            "label": "Runtime (for docs)",
            "type": "select",
            "options": [
                "python312", "python311", "nodejs20", "nodejs18",
                "go122", "java21", "dotnet8",
            ],
            "default": "python312",
        },
        {
            "key": "region",
            "label": "Region",
            "type": "select",
            "options": ["me-west1", "us-central1", "us-east1", "europe-west1"],
            "default": "me-west1",
        },
        {
            "key": "trigger_type",
            "label": "Trigger Type (for docs)",
            "type": "select",
            "options": ["HTTP", "Pub/Sub", "Cloud Storage", "Firestore", "Eventarc"],
            "default": "HTTP",
        },
    ]

    inputs:  ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("callers",      PortType.HTTP_TARGET, multi=True),  # callers wired TO this fn
        Port("publishes_to", PortType.TOPIC,       multi=True),  # fn publishes to topic
        Port("writes_to",    PortType.STORAGE,     multi=True),  # fn writes to GCS
    ]

    node_color:  ClassVar = "#10b981"
    icon:        ClassVar = "cloudFunctions"
    category:    ClassVar = "Compute"
    description: ClassVar = "Cloud Functions stub (visual reference)"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id:
            if tgt_type in ("CloudRunNode", "WorkflowNode"):
                ctx[tgt_id].setdefault("visual_api_ids", []).append(self.node_id)
                return True
            if tgt_type == "GcsBucketNode":
                ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
                return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        def program() -> None:
            name = props.get("name") or _resource_name(node_dict)
            url  = props.get("function_url", "")
            pulumi.export("url",  url)
            pulumi.export("name", name)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "url":  pulumi_outputs.get("url",  ""),
            "name": pulumi_outputs.get("name", ""),
        }

    def log_source(self, pulumi_outputs, project, region):
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        from nodes.base_node import LogSource
        return LogSource(
            filter=(
                f'resource.type="cloud_function"'
                f' AND resource.labels.function_name="{name}"'
            ),
            project=project,
        )


# ── Generic External API (visual-only) ───────────────────────────────────────

@dataclass
class ExternalApiNode(GCPNode):
    """
    External / third-party API — visual stub.

    Use this when your architecture calls any external HTTP endpoint
    (Stripe, SendGrid, a partner API, etc.) and you want to document
    the dependency on the canvas without deploying anything.

    The URL is injected as EXTERNAL_API_URL_<NAME> into connected callers.
    """

    params_schema: ClassVar = [
        {
            "key": "name",
            "label": "API Name",
            "type": "text",
            "default": "",
            "placeholder": "payment-gateway",
        },
        {
            "key": "base_url",
            "label": "Base URL",
            "type": "text",
            "default": "",
            "placeholder": "https://api.example.com/v1",
        },
        {
            "key": "description",
            "label": "Notes",
            "type": "text",
            "default": "",
            "placeholder": "What this API is used for",
        },
    ]

    inputs:  ClassVar = []
    outputs: ClassVar = [
        Port("callers", PortType.HTTP_TARGET, multi=True),
    ]

    node_color:  ClassVar = "#94a3b8"
    icon:        ClassVar = "externalApi"
    category:    ClassVar = "External"
    description: ClassVar = "External API reference (no resource created)"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and tgt_type in ("CloudRunNode", "WorkflowNode"):
            ctx[tgt_id].setdefault("visual_api_ids", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        def program() -> None:
            name = props.get("name") or _resource_name(node_dict)
            url  = props.get("base_url", "")
            pulumi.export("url",  url)
            pulumi.export("name", name)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "url":  pulumi_outputs.get("url",  ""),
            "name": pulumi_outputs.get("name", ""),
        }

    def log_source(self, pulumi_outputs, project, region):
        return None
