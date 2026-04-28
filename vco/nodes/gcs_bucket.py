"""
nodes/gcs_bucket.py — Cloud Storage Bucket resource node (fully self-describing).

Topology
--------
  GcsBucketNode ──(STORAGE)──► CloudRunNode      (env: GCS_BUCKET_<NAME>)
  GcsBucketNode ──(BUCKET)───► EventarcTriggerNode

  CloudRunNode  ──(STORAGE)──► GcsBucketNode  ← writers wired IN
  WorkflowNode  ──(STORAGE)──► GcsBucketNode  ← writers wired IN

Writers wired INTO the bucket input port get:
  • GCS_BUCKET_<BUCKET_NAME> env var injected into them (for CR)
  • bucket name exported to deployed_outputs (for Workflows YAML)

The bucket also grants the wired writer's SA (if any) roles/storage.objectCreator
so the Cloud Run / Workflow SA can write without extra IAM steps.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class GcsBucketNode(GCPNode):
    """
    Cloud Storage Bucket.

    Inputs  (writers)  : any compute node that writes objects → bucket grants it objectCreator
    Outputs (consumers): STORAGE → CloudRun (env var), BUCKET → Eventarc (trigger source)
    """

    params_schema: ClassVar = [
        {
            "key": "name", "label": "Bucket Name",
            "type": "text", "default": "", "placeholder": "my-project-bucket",
        },
        {
            "key": "location", "label": "Location",
            "type": "select",
            "options": ["EU", "US", "ASIA", "me-west1", "us-central1", "us-east1", "europe-west1"],
            "default": "EU",
        },
        {
            "key": "storage_class", "label": "Storage Class",
            "type": "select",
            "options": ["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"],
            "default": "STANDARD",
        },
        {"key": "versioning",     "label": "Object Versioning",             "type": "boolean", "default": False},
        {"key": "uniform_access", "label": "Uniform Bucket-Level Access",   "type": "boolean", "default": True},
        {"key": "lifecycle_age",  "label": "Auto-delete after N days (0=off)", "type": "number", "default": 0},
        {"key": "public_access",  "label": "Allow Public Read",             "type": "boolean", "default": False},
    ]

    inputs: ClassVar = [
        # Nodes that WRITE to this bucket (CR, Workflows, etc.)
        # Wiring here causes: env-var injection into writer + IAM objectCreator grant
        Port("writers",         PortType.STORAGE,         required=False, multi=True, multi_in=True),
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("storage", PortType.STORAGE, multi=True),   # → CloudRun (env var reader)
        Port("events",  PortType.BUCKET,  multi=True),   # → EventarcTriggerNode
    ]

    node_color:  ClassVar = "#fbbf24"
    icon:        ClassVar = "gcsBucket"
    category:    ClassVar = "Storage"
    description: ClassVar = "Cloud Storage Bucket"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ── Output edges: this bucket → consumers ──────────────────────────
        if src_id == self.node_id:
            # STORAGE output → CloudRunNode: inject bucket name as env var
            if tgt_type == "CloudRunNode":
                ctx[tgt_id].setdefault("bucket_ids", []).append(self.node_id)
                return True
            # BUCKET output → EventarcTriggerNode: set as event source
            if tgt_type == "EventarcTriggerNode":
                ctx[tgt_id]["bucket_source_id"] = self.node_id
                return True

        # ── Input edges: writers → this bucket ────────────────────────────
        if tgt_id == self.node_id:
            # CloudRunNode/WorkflowNode → bucket: register as writer
            if src_type in ("CloudRunNode", "WorkflowNode"):
                ctx[self.node_id].setdefault("writer_ids", []).append(src_id)
                # Also tell the writer about the bucket so it gets env vars
                ctx[src_id].setdefault("bucket_ids", []).append(self.node_id)
                return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        # Writers must be deployed first so we can read their SA emails for IAM
        return list(ctx.get("writer_ids", []))

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        writer_ids = ctx.get("writer_ids", [])

        def program() -> None:
            bucket_name   = props.get("name") or _resource_name(node_dict)
            location      = props.get("location", "EU")
            storage_class = props.get("storage_class", "STANDARD")
            versioning    = props.get("versioning", False)
            uniform       = props.get("uniform_access", True)
            lifecycle_age = int(props.get("lifecycle_age", 0))
            public_access = props.get("public_access", False)

            lifecycle_rules = []
            if lifecycle_age > 0:
                lifecycle_rules.append(
                    gcp.storage.BucketLifecycleRuleArgs(
                        action=gcp.storage.BucketLifecycleRuleActionArgs(type="Delete"),
                        condition=gcp.storage.BucketLifecycleRuleConditionArgs(age=lifecycle_age),
                    )
                )

            b = gcp.storage.Bucket(
                self.node_id,
                name=bucket_name,
                location=location,
                storage_class=storage_class,
                project=project,
                uniform_bucket_level_access=uniform,
                versioning=(
                    gcp.storage.BucketVersioningArgs(enabled=True) if versioning else None
                ),
                lifecycle_rules=lifecycle_rules or None,
                force_destroy=True,
            )

            # ── Public read IAM ───────────────────────────────────────────────
            if public_access:
                gcp.storage.BucketIAMBinding(
                    f"{self.node_id}-public-read",
                    bucket=b.name,
                    role="roles/storage.objectViewer",
                    members=["allUsers"],
                )

            # ── Grant objectCreator to every wired writer SA ──────────────────
            # Collect unique SA emails from deployed_outputs of writer nodes
            sa_emails: list[str] = []
            for wid in writer_ids:
                email = deployed_outputs.get(wid, {}).get("sa_email", "")
                if not email:
                    # CloudRunNode exports its SA email under "sa_email" if set,
                    # otherwise fall back to the generic service account export
                    email = deployed_outputs.get(wid, {}).get("email", "")
                if email and email not in sa_emails:
                    sa_emails.append(email)

            if sa_emails:
                gcp.storage.BucketIAMBinding(
                    f"{self.node_id}-writer-binding",
                    bucket=b.name,
                    role="roles/storage.objectCreator",
                    members=[f"serviceAccount:{e}" for e in sa_emails],
                )

            pulumi.export("name", b.name)
            pulumi.export("url",  b.url)
            pulumi.export("id",   b.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "name": pulumi_outputs.get("name", ""),
            "url":  pulumi_outputs.get("url",  ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="gcs_bucket"'
                f' AND resource.labels.bucket_name="{name}"'
            ),
            project=project,
        )