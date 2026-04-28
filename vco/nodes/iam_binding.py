"""
nodes/iam_binding.py — IAM Binding / Role Grant node (fully self-describing).

Topology
--------
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► IamBindingNode

This node grants one or more IAM roles to a wired ServiceAccount on a
given resource scope (project, bucket, topic, etc.).

It is the canonical way to give a Service Account the permissions it needs
without hardcoding roles inside other nodes.

Typical use-cases shown in architecture diagrams:
  • Grant Cloud Run SA  → roles/datastore.user         (Firestore access)
  • Grant Cloud Run SA  → roles/storage.objectCreator  (GCS write)
  • Grant Workflow SA   → roles/run.invoker            (call Cloud Run)
  • Grant Scheduler SA  → roles/cloudtasks.enqueuer    (enqueue tasks)

Scope options
-------------
  project           — projects/<project>
  bucket            — buckets/<bucket_name>
  topic             — projects/<project>/topics/<topic>
  service_account   — projects/<project>/serviceAccounts/<sa_email>
  custom            — raw resource string (advanced)

Exports
-------
  binding_id  — Pulumi resource id of the created IAM binding
  role        — the role that was granted
  member      — the member the role was granted to
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# Common roles for the dropdown
_COMMON_ROLES = [
    "roles/run.invoker",
    "roles/datastore.user",
    "roles/storage.objectCreator",
    "roles/storage.objectViewer",
    "roles/storage.admin",
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/cloudtasks.enqueuer",
    "roles/cloudscheduler.jobRunner",
    "roles/workflows.invoker",
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/artifactregistry.reader",
    "roles/iam.serviceAccountTokenCreator",
    "roles/editor",
    "roles/viewer",
    "custom",
]

_SCOPE_OPTIONS = ["project", "bucket", "topic", "service_account", "custom"]


@dataclass
class IamBindingNode(GCPNode):
    """
    IAM Role Binding — grant a role to a Service Account.

    Wire a ServiceAccountNode into this node's input, then configure:
      - role       : the IAM role to grant
      - scope_type : where the role is granted (project / bucket / topic / …)
      - scope_value: the resource identifier (bucket name, topic name, etc.)
                     Leave empty for project-level scope.

    For custom roles or scope strings, pick "custom" in the dropdowns
    and fill in the raw values.
    """

    params_schema: ClassVar = [
        {
            "key": "role",
            "label": "IAM Role",
            "type": "select",
            "options": _COMMON_ROLES,
            "default": "roles/run.invoker",
        },
        {
            "key": "custom_role",
            "label": "Custom Role (if 'custom' selected above)",
            "type": "text",
            "default": "",
            "placeholder": "roles/my.customRole",
            "show_if": {"role": "custom"},
        },
        {
            "key": "scope_type",
            "label": "Scope",
            "type": "select",
            "options": _SCOPE_OPTIONS,
            "default": "project",
        },
        {
            "key": "scope_value",
            "label": "Scope Value (bucket/topic/SA name — empty = project)",
            "type": "text",
            "default": "",
            "placeholder": "my-bucket  OR  my-topic  OR  sa@project.iam.gserviceaccount.com",
        },
    ]

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
    ]
    outputs: ClassVar = []   # terminal node — no downstream connections needed

    node_color:  ClassVar = "#7c3aed"
    icon:        ClassVar = "iam_binding"
    category:    ClassVar = "IAM"
    description: ClassVar = "Grant an IAM role to a Service Account"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ServiceAccountNode → IamBindingNode
        if tgt_id == self.node_id and src_type == "ServiceAccountNode":
            ctx[self.node_id]["service_account_id"] = src_id
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        sa_id = ctx.get("service_account_id")
        return [sa_id] if sa_id else []

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "")

        def program() -> None:
            if not sa_email:
                logger.warning(
                    "IamBindingNode %s: no SA email resolved — skipping binding",
                    self.node_id,
                )
                return

            role = props.get("role", "roles/run.invoker")
            if role == "custom":
                role = props.get("custom_role", "").strip()
            if not role:
                logger.error("IamBindingNode %s: no role configured", self.node_id)
                return

            scope_type  = props.get("scope_type",  "project")
            scope_value = props.get("scope_value", "").strip()
            member      = f"serviceAccount:{sa_email}"

            # ── Project-level binding ──────────────────────────────────────
            if scope_type == "project" or not scope_value:
                binding = gcp.projects.IAMMember(
                    self.node_id,
                    project=project,
                    role=role,
                    member=member,
                )
                pulumi.export("binding_id", binding.id)

            # ── Bucket-level binding ───────────────────────────────────────
            elif scope_type == "bucket":
                binding = gcp.storage.BucketIAMMember(
                    self.node_id,
                    bucket=scope_value,
                    role=role,
                    member=member,
                )
                pulumi.export("binding_id", binding.id)

            # ── Pub/Sub topic binding ──────────────────────────────────────
            elif scope_type == "topic":
                topic_path = f"projects/{project}/topics/{scope_value}"
                binding = gcp.pubsub.TopicIAMMember(
                    self.node_id,
                    topic=topic_path,
                    role=role,
                    member=member,
                )
                pulumi.export("binding_id", binding.id)

            # ── Service-account impersonation binding ──────────────────────
            elif scope_type == "service_account":
                binding = gcp.serviceaccount.IAMMember(
                    self.node_id,
                    service_account_id=f"projects/{project}/serviceAccounts/{scope_value}",
                    role=role,
                    member=member,
                )
                pulumi.export("binding_id", binding.id)

            # ── Custom / raw resource binding → project-level fallback ─────
            else:
                binding = gcp.projects.IAMMember(
                    self.node_id,
                    project=project,
                    role=role,
                    member=member,
                )
                pulumi.export("binding_id", binding.id)

            pulumi.export("role",   role)
            pulumi.export("member", member)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "role":   pulumi_outputs.get("role",   ""),
            "member": pulumi_outputs.get("member", ""),
        }

    def log_source(self, pulumi_outputs, project, region):
        return None   # IAM bindings have no log stream
