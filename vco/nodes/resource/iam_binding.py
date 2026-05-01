"""
nodes/iam_binding.py — Standalone IAM Binding node (fully self-describing).

Purpose
-------
Grants a GCP IAM role to any principal (SA email, user, group, or special
identifiers such as allUsers) on either:

  a) the entire PROJECT  (project-level binding)
  b) a specific RESOURCE  (resource-level binding)

NEW: Connect a ServiceAccountNode to auto-fill the principal from the deployed
SA email — no need to type the email manually.

Topology
--------
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► IamBindingNode  ← NEW (auto-fill principal)

  IamBindingNode ──(IAM_BINDING)──► CloudRunNode
  IamBindingNode ──(IAM_BINDING)──► GcsBucketNode
  IamBindingNode ──(IAM_BINDING)──► WorkflowNode
  IamBindingNode ──(IAM_BINDING)──► CloudTasksQueueNode
  IamBindingNode ──(IAM_BINDING)──► CloudFunctionsNode
  IamBindingNode ──(IAM_BINDING)──► EventarcTriggerNode

  IamBindingNode (no output edge) → project-level binding only

Wiring behaviour
----------------
When a ServiceAccountNode is wired in:
  - The SA email is read from deployed_outputs at deploy time
  - principal field is IGNORED (wired SA takes priority)
  - member string becomes: serviceAccount:<deployed_email>

When no SA is wired:
  - principal field is used as-is (must be a valid member string)

When an IamBindingNode is wired into a resource node via IAM_BINDING port:
  - resource_type is auto-detected from the target node type
  - resource_ref  is auto-set to the target node id
  - The user only needs to fill in: resource_role (and optionally project_role)

Examples covered by this node
------------------------------

  # Cloud Storage service agent → Pub/Sub publisher (for Eventarc GCS triggers)
  gcloud projects add-iam-policy-binding ${PROJECT} \\
    --member="serviceAccount:${CLOUD_STORAGE_SA}" \\
    --role="roles/pubsub.publisher"

  # Workflow trigger SA → Eventarc event receiver
  gcloud projects add-iam-policy-binding ${PROJECT} \\
    --member "serviceAccount:${WORKFLOW_TRIGGER_SA}@${PROJECT}.iam.gserviceaccount.com" \\
    --role="roles/eventarc.eventReceiver"

  # Collage schedule SA → Cloud Run invoker on specific service
  gcloud run services add-iam-policy-binding ${COLLAGE_SERVICE} \\
    --region=${REGION} \\
    --member="serviceAccount:${COLLAGE_SCHED_SA}@${PROJECT}.iam.gserviceaccount.com" \\
    --role="roles/run.invoker"

  # Delete trigger SA → Cloud Run invoker
  gcloud run services add-iam-policy-binding ${DELETE_SERVICE} \\
    --region=${DELETE_SERVICE_REGION} \\
    --member="serviceAccount:${DELETE_TRIGGER_SA}@${PROJECT}.iam.gserviceaccount.com" \\
    --role="roles/run.invoker"

Parameters (params_schema)
--------------------------
  principal      text    Full member string (ignored when SA is wired in):
                           serviceAccount:my-sa@project.iam.gserviceaccount.com
                           user:someone@example.com
                           allUsers
                           allAuthenticatedUsers

  project_role   text    Role to grant at project level (blank = skip project binding).
                           e.g. roles/pubsub.publisher

  resource_role  text    Role to grant on the wired resource (blank = skip resource binding).
                           e.g. roles/run.invoker

Exports
-------
  principal  — the member string used
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

# Map from target node type → how to extract the resource identifier
# and which Pulumi IAM resource to create.
_RESOURCE_TYPE_MAP: dict[str, str] = {
    "CloudRunNode":          "cloud_run_service",
    "GcsBucketNode":         "gcs_bucket",
    "WorkflowNode":          "workflow",
    "CloudTasksQueueNode":   "cloud_tasks_queue",
    "CloudFunctionsNode":    "cloud_function",
    "EventarcTriggerNode":   "eventarc_trigger",
}


@dataclass
class IamBindingNode(GCPNode):
    """
    Standalone IAM Binding node.

    Grants a role to any principal (SA, user, group, allUsers) at:
      - project level  (project_role field)
      - resource level (resource_role field + IAM_BINDING output edge)

    Connect a ServiceAccountNode → auto-fills principal from deployed SA email.
    Connect via IAM_BINDING output to a resource node to scope the resource binding.
    Leave unconnected for project-only grants.
    """

    params_schema: ClassVar = [
        {
            "key":         "principal",
            "label":       "Principal (member string — ignored when SA is wired)",
            "type":        "text",
            "default":     "",
            "placeholder": "serviceAccount:my-sa@project.iam.gserviceaccount.com",
        },
        {
            "key":         "project_role",
            "label":       "Project-Level Role (leave blank to skip)",
            "type":        "text",
            "default":     "",
            "placeholder": "roles/pubsub.publisher",
        },
        {
            "key":         "resource_role",
            "label":       "Resource-Level Role (requires output edge)",
            "type":        "text",
            "default":     "",
            "placeholder": "roles/run.invoker",
        },
    ]

    # NEW: accepts a ServiceAccountNode as input to auto-fill the principal
    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("grants_on", PortType.IAM_BINDING, multi=True),
    ]

    node_color:  ClassVar = "#34d399"
    icon:        ClassVar = "identity_and_access_management"
    category:    ClassVar = "IAM"
    description: ClassVar = (
        "Grants IAM roles to any principal at project level "
        "and/or resource level (connect to target resource). "
        "Wire a ServiceAccountNode to auto-fill the principal."
    )

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ServiceAccountNode → IamBindingNode: auto-fill principal from SA email
        if tgt_id == self.node_id and src_type == "ServiceAccountNode":
            ctx[self.node_id]["service_account_id"] = src_id
            return True

        # IamBindingNode → resource node: record the target binding
        if src_id == self.node_id and src_type == "IamBindingNode":
            detected = _RESOURCE_TYPE_MAP.get(tgt_type, "unknown")
            ctx[self.node_id].setdefault("target_bindings", []).append({
                "node_id":       tgt_id,
                "resource_type": detected,
            })
            return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = [b["node_id"] for b in ctx.get("target_bindings", [])]
        # SA must be deployed before we can read its email
        sa_id = ctx.get("service_account_id")
        if sa_id:
            deps.append(sa_id)
        return deps

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

        # ── Resolve principal ─────────────────────────────────────────────────
        # Priority: wired SA > explicit principal field
        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "").strip() if sa_id else ""

        principal     = props.get("principal", "").strip()
        project_role  = props.get("project_role",  "").strip()
        resource_role = props.get("resource_role", "").strip()
        target_bindings = ctx.get("target_bindings", [])

        if sa_email:
            # SA wired — build member string from deployed email
            resolved_principal = f"serviceAccount:{sa_email}"
        elif principal:
            resolved_principal = principal
        else:
            logger.error(
                "IamBindingNode %s: no SA wired and 'principal' is empty — skipping",
                self.node_id,
            )
            return None

        def program() -> None:
            member = resolved_principal

            # ── 1. Project-level binding ──────────────────────────────────
            # Equivalent:
            #   gcloud projects add-iam-policy-binding ${PROJECT} \
            #     --member="serviceAccount:..." \
            #     --role="roles/..."
            if project_role:
                gcp.projects.IAMMember(
                    f"{self.node_id}-proj",
                    project=project,
                    role=project_role,
                    member=member,
                )
                logger.info(
                    "IamBindingNode %s: project binding %s → %s",
                    self.node_id, member, project_role,
                )

            # ── 2. Resource-level bindings ────────────────────────────────
            for idx, binding in enumerate(target_bindings):
                tgt_id  = binding["node_id"]
                rtype   = binding["resource_type"]
                outputs = deployed_outputs.get(tgt_id, {})

                if not resource_role:
                    logger.warning(
                        "IamBindingNode %s: resource_role is empty for target %s — skip",
                        self.node_id, tgt_id,
                    )
                    continue

                _create_resource_iam_member(
                    resource_id   = f"{self.node_id}-res-{idx}",
                    resource_type = rtype,
                    role          = resource_role,
                    member        = member,
                    outputs       = outputs,
                    project       = project,
                    region        = region,
                )

            pulumi.export("principal", resolved_principal)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {}

    def log_source(self, pulumi_outputs, project, region):
        return None


# ── IAM resource factory ──────────────────────────────────────────────────────

def _create_resource_iam_member(
    resource_id:   str,
    resource_type: str,
    role:          str,
    member:        str,
    outputs:       dict,
    project:       str,
    region:        str,
) -> None:
    """
    Create a Pulumi IAM member resource for a specific GCP resource type.

    resource_type values (auto-detected from connected node type):
      cloud_run_service   → gcp.cloudrun.IamMember
      gcs_bucket          → gcp.storage.BucketIAMMember
      workflow            → gcp.projects.IAMMember  (project-level fallback)
      cloud_tasks_queue   → gcp.cloudtasks.QueueIamMember
      cloud_function      → gcp.cloudfunctions.FunctionIamMember
      eventarc_trigger    → gcp.projects.IAMMember  (project-level fallback)
      unknown             → gcp.projects.IAMMember  (fallback)
    """

    if resource_type == "cloud_run_service":
        svc_name = outputs.get("name", "")
        if not svc_name:
            logger.warning("IamBindingNode %s: missing 'name' from CloudRunNode outputs", resource_id)
            return
        # gcloud run services add-iam-policy-binding ${SERVICE} \
        #   --region=${REGION} --member=... --role=...
        gcp.cloudrun.IamMember(
            resource_id,
            location=region,
            project=project,
            service=svc_name,
            role=role,
            member=member,
        )

    elif resource_type == "gcs_bucket":
        bucket_name = outputs.get("name", "")
        if not bucket_name:
            logger.warning("IamBindingNode %s: missing 'name' from GcsBucketNode outputs", resource_id)
            return
        # gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \
        #   --member=... --role=...
        gcp.storage.BucketIAMMember(
            resource_id,
            bucket=bucket_name,
            role=role,
            member=member,
        )

    elif resource_type == "workflow":
        # pulumi_gcp does not expose a WorkflowIamMember resource.
        # Workflows IAM is managed at project level via projects.IAMMember.
        # Equivalent:
        #   gcloud projects add-iam-policy-binding ${PROJECT} \
        #     --member="serviceAccount:..." \
        #     --role="roles/workflows.invoker"
        logger.warning(
            "IamBindingNode %s: pulumi_gcp has no WorkflowIamMember — "
            "falling back to project-level IAMMember for role '%s'",
            resource_id, role,
        )
        gcp.projects.IAMMember(
            resource_id,
            project=project,
            role=role,
            member=member,
        )

    elif resource_type == "cloud_tasks_queue":
        queue_name = outputs.get("queue_name", "")
        if not queue_name:
            logger.warning("IamBindingNode %s: missing 'queue_name' from CloudTasksQueueNode outputs", resource_id)
            return
        gcp.cloudtasks.QueueIamMember(
            resource_id,
            project=project,
            location=region,
            name=queue_name,
            role=role,
            member=member,
        )

    elif resource_type == "cloud_function":
        fn_name = outputs.get("name", "")
        if not fn_name:
            logger.warning("IamBindingNode %s: missing 'name' from CloudFunctionsNode outputs", resource_id)
            return
        # gcloud functions add-iam-policy-binding ${FUNCTION_NAME} \
        #   --member=... --role=roles/cloudfunctions.invoker
        gcp.cloudfunctions.FunctionIamMember(
            resource_id,
            project=project,
            region=region,
            cloud_function=fn_name,
            role=role,
            member=member,
        )

    elif resource_type == "eventarc_trigger":
        # pulumi_gcp (≤9.x) does not expose an EventarcTriggerIamMember.
        # Falls back to project-level.
        logger.warning(
            "IamBindingNode %s: pulumi_gcp has no TriggerIamMember — "
            "falling back to project-level IAMMember for role '%s'",
            resource_id, role,
        )
        gcp.projects.IAMMember(
            resource_id,
            project=project,
            role=role,
            member=member,
        )

    else:
        logger.warning(
            "IamBindingNode %s: unknown resource_type '%s' — falling back to project-level binding",
            resource_id, resource_type,
        )
        gcp.projects.IAMMember(
            resource_id,
            project=project,
            role=role,
            member=member,
        )