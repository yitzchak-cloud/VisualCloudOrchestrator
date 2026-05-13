"""
nodes/resource/iam_binding/iam_binding.py
──────────────────────────────────────────────────────────────────────────────
IamBindingNode — standalone IAM Binding node.

Grants a GCP IAM role to any principal (SA email, user, group, or special
identifiers such as allUsers) at:
  a) the entire PROJECT  (project_role field)
  b) a specific RESOURCE (resource_role field + IAM_BINDING output edge)

Connect a ServiceAccountNode → principal is auto-filled from deployed SA email.
Leave output edge unconnected → project-only grant.

What changed vs previous version
─────────────────────────────────
* params_schema moved to iam_binding_params.yaml (categories + descriptions).
* Pulumi cloud_run_service uses cloudrunv2.ServiceIamMember (not v1 cloudrun).
* Terraform fully implemented:
    - terraform_blocks()          inline HCL blocks
    - terraform_call_vars()       module variable dict
    - terraform_instance_prefix   property
    - terraform/ module files     variables.tf / main.tf / outputs.tf
* live_outputs now returns principal so it shows on the canvas after deploy.
* _create_resource_iam_member refactored into a dispatch table for clarity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import (
    GCPNode, LogSource, Port, TFBlock, TFResult,
    _resource_name, _tf_name, _node_by_id,
)
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# ── Resource type → metadata used by both Pulumi and Terraform ────────────────
# Each entry: (pulumi_handler_key, tf_resource_type, tf_name_output_key)
_RESOURCE_TYPE_MAP: dict[str, str] = {
    "CloudRunNode":              "cloud_run_service",
    "GcsBucketNode":             "gcs_bucket",
    "WorkflowNode":              "workflow",
    "CloudTasksQueueNode":       "cloud_tasks_queue",
    "CloudFunctionsNode":        "cloud_function",
    "EventarcTriggerNode":       "eventarc_trigger",
    "PubsubSubscriptionNode":    "pubsub_subscription",
    "PubsubTopicNode":           "pubsub_topic",
}

# Terraform resource types for each GCP resource kind
_TF_RESOURCE: dict[str, str] = {
    "cloud_run_service":   "google_cloud_run_v2_service_iam_member",
    "gcs_bucket":          "google_storage_bucket_iam_member",
    "workflow":            "google_project_iam_member",          # no TF resource-level workflow IAM
    "cloud_tasks_queue":   "google_cloud_tasks_queue_iam_member",
    "cloud_function":      "google_cloudfunctions_function_iam_member",
    "eventarc_trigger":    "google_project_iam_member",          # no TF resource-level eventarc IAM
    "pubsub_subscription": "google_pubsub_subscription_iam_member",
    "pubsub_topic":        "google_pubsub_topic_iam_member",
    "unknown":             "google_project_iam_member",
}


@dataclass
class IamBindingNode(GCPNode):
    """
    Standalone IAM Binding node.

    Grants a role to any principal (SA, user, group, allUsers) at:
      - project level  (project_role field)
      - resource level (resource_role field + IAM_BINDING output edge)

    Wire a ServiceAccountNode in → principal auto-filled from deployed SA email.
    Wire output edge to resource node → resource-level binding on that resource.
    Leave output unconnected → project-only grant.
    """

    # params loaded from iam_binding_params.yaml automatically by base_node

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

    # ──────────────────────────────────────────────────────────────────────────
    # Edge wiring
    # ──────────────────────────────────────────────────────────────────────────

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

    # ──────────────────────────────────────────────────────────────────────────
    # DAG dependencies
    # ──────────────────────────────────────────────────────────────────────────

    def dag_deps(self, ctx) -> list[str]:
        # All target resources must be deployed before IAM bindings can reference them
        deps = [b["node_id"] for b in ctx.get("target_bindings", [])]
        # SA must be deployed before we can read its email
        sa_id = ctx.get("service_account_id")
        if sa_id:
            deps.append(sa_id)
        return deps

    # ──────────────────────────────────────────────────────────────────────────
    # Pulumi program
    # ──────────────────────────────────────────────────────────────────────────

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
        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "").strip() if sa_id else ""

        principal     = props.get("principal",    "").strip()
        project_role  = props.get("project_role",  "").strip()
        resource_role = props.get("resource_role", "").strip()
        target_bindings = ctx.get("target_bindings", [])

        if sa_email:
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

            # ── 1. Project-level binding ──────────────────────────────────────
            if project_role:
                gcp.projects.IAMMember(
                    f"{self.node_id}-proj",
                    project=project,
                    role=project_role,
                    member=member,
                )

            # ── 2. Resource-level bindings ────────────────────────────────────
            for idx, binding in enumerate(target_bindings):
                tgt_id  = binding["node_id"]
                rtype   = binding["resource_type"]
                outputs = deployed_outputs.get(tgt_id, {})

                if not resource_role:
                    logger.warning(
                        "IamBindingNode %s: resource_role empty for target %s — skip",
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

            pulumi.export("principal", member)

        return program

    # ──────────────────────────────────────────────────────────────────────────
    # Terraform — inline blocks
    # ──────────────────────────────────────────────────────────────────────────

    def terraform_blocks(self, ctx, project, region, all_nodes) -> TFResult:
        result    = TFResult()
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        tf_id     = _tf_name(node_dict)

        project_role    = props.get("project_role",  "").strip()
        resource_role   = props.get("resource_role", "").strip()
        principal       = props.get("principal",     "").strip()
        target_bindings = ctx.get("target_bindings", [])

        # SA: if wired, member = google_service_account.<tf_id>.email
        sa_id   = ctx.get("service_account_id", "")
        sa_node = _node_by_id(all_nodes, sa_id) if sa_id else None
        if sa_node:
            if sa_node.get("props", {}).get("create_sa", True):
                member = f"serviceAccount:${{google_service_account.{_tf_name(sa_node)}.email}}"
            else:
                member = f"serviceAccount:{sa_node.get('props',{}).get('email','')}"
        elif principal:
            member = principal
        else:
            logger.error("IamBindingNode %s: no principal resolved for TF — skipping", self.node_id)
            return result

        # ── Project-level binding ─────────────────────────────────────────────
        if project_role:
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_project_iam_member", f"{tf_id}_proj"],
                body={
                    "project": "var.project_id",
                    "role":    project_role,
                    "member":  member,
                },
                comment=f"IAM binding (project): {member} → {project_role}",
            ))

        # ── Resource-level bindings ───────────────────────────────────────────
        if resource_role:
            for idx, binding in enumerate(target_bindings):
                tgt_id  = binding["node_id"]
                rtype   = binding["resource_type"]
                tgt_node = _node_by_id(all_nodes, tgt_id)
                tf_tgt   = _tf_name(tgt_node) if tgt_node else ""
                res_tf   = _TF_RESOURCE.get(rtype, "google_project_iam_member")
                bind_id  = f"{tf_id}_res_{idx}"

                body: dict = {"role": resource_role, "member": member}

                if rtype == "cloud_run_service":
                    body["project"]  = "var.project_id"
                    body["location"] = "var.region"
                    body["name"]     = f"${{google_cloud_run_v2_service.{tf_tgt}.name}}"

                elif rtype == "gcs_bucket":
                    body["bucket"] = f"${{google_storage_bucket.{tf_tgt}.name}}"

                elif rtype == "cloud_tasks_queue":
                    body["project"]  = "var.project_id"
                    body["location"] = "var.region"
                    body["name"]     = f"${{google_cloud_tasks_queue.{tf_tgt}.name}}"

                elif rtype == "cloud_function":
                    body["project"]        = "var.project_id"
                    body["region"]         = "var.region"
                    body["cloud_function"] = f"${{google_cloudfunctions_function.{tf_tgt}.name}}"

                elif rtype == "pubsub_subscription":
                    body["project"]      = "var.project_id"
                    body["subscription"] = f"${{google_pubsub_subscription.{tf_tgt}.name}}"

                elif rtype == "pubsub_topic":
                    body["project"] = "var.project_id"
                    body["topic"]   = f"${{google_pubsub_topic.{tf_tgt}.name}}"

                else:
                    # workflow / eventarc_trigger / unknown → project-level fallback
                    body["project"] = "var.project_id"
                    logger.warning(
                        "IamBindingNode %s: rtype '%s' has no resource-level TF resource — "
                        "falling back to google_project_iam_member",
                        tf_id, rtype,
                    )

                result.resources.append(TFBlock(
                    block_type="resource",
                    labels=[res_tf, bind_id],
                    body=body,
                    comment=f"IAM binding ({rtype}): {member} → {resource_role}",
                ))

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Terraform — static module interface
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return "iam"

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        # ── Resolve member ────────────────────────────────────────────────────
        sa_id   = ctx.get("service_account_id", "")
        sa_node = _node_by_id(all_nodes, sa_id) if sa_id else None
        if sa_node:
            if sa_node.get("props", {}).get("create_sa", True):
                member = f"serviceAccount:${{module.sa_{_tf_name(sa_node)}.email}}"
            else:
                member = f"serviceAccount:{sa_node.get('props', {}).get('email', '')}"
        else:
            member = props.get("principal", "")

        cv: dict[str, str] = {
            "member":        f'"{member}"',
            "project_role":  f'"{props.get("project_role",  "")}"',
            "resource_role": f'"{props.get("resource_role", "")}"',
        }

        # ── Resource-level: one var per resource type ─────────────────────────
        # Maps rtype → (module_var_name, module_prefix)
        # pubsub_subscription is handled separately (dynamic prefix push/pull)
        _MODULE_PREFIX: dict[str, tuple[str, str]] = {
            "cloud_run_service":   ("cloud_run_service_name",   "cr"),
            "gcs_bucket":          ("gcs_bucket_name",          "gcs"),
            "cloud_tasks_queue":   ("cloud_tasks_queue_name",   "tasks_queue"),
            "cloud_function":      ("cloud_function_name",      "func"),
            "pubsub_topic":        ("pubsub_topic_name",        "topic"),
        }

        # Initialise all resource vars to empty (disabled)
        for var_name, _ in _MODULE_PREFIX.values():
            cv[var_name] = '""'
        cv["pubsub_subscription_name"] = '""'

        # Override vars for wired targets
        for binding in ctx.get("target_bindings", []):
            rtype    = binding["resource_type"]
            tgt_node = _node_by_id(all_nodes, binding["node_id"])
            if not tgt_node:
                continue

            tgt_tf_name = _tf_name(tgt_node)

            if rtype == "pubsub_subscription":
                sub_type      = tgt_node.get("props", {}).get("subscription_type", "pull")
                module_prefix = "push_sub" if sub_type == "push" else "pull_sub"
                cv["pubsub_subscription_name"] = f"module.{module_prefix}_{tgt_tf_name}.name"

            elif rtype in _MODULE_PREFIX:
                var_name, module_prefix = _MODULE_PREFIX[rtype]
                cv[var_name] = f"module.{module_prefix}_{tgt_tf_name}.name"

            else:
                # workflow / eventarc_trigger / unknown → no resource-level TF support
                logger.warning(
                    "IamBindingNode %s: rtype '%s' has no module-level TF support — skipping",
                    self.node_id, rtype,
                )

        return cv

    # ──────────────────────────────────────────────────────────────────────────
    # Post-deploy
    # ──────────────────────────────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"principal": pulumi_outputs.get("principal", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return None


# ── Pulumi IAM resource factory ───────────────────────────────────────────────

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

    Dispatch table:
      cloud_run_service  → gcp.cloudrunv2.ServiceIamMember     (v2, not v1)
      gcs_bucket         → gcp.storage.BucketIAMMember
      workflow           → gcp.projects.IAMMember               (no SDK resource-level)
      cloud_tasks_queue  → gcp.cloudtasks.QueueIamMember
      cloud_function     → gcp.cloudfunctions.FunctionIamMember
      eventarc_trigger   → gcp.projects.IAMMember               (no SDK resource-level)
      unknown            → gcp.projects.IAMMember               (fallback)
    """

    if resource_type == "cloud_run_service":
        svc_name = outputs.get("name", "")
        if not svc_name:
            logger.warning("IamBindingNode %s: missing 'name' from CloudRunNode outputs", resource_id)
            return
        # Uses cloudrunv2 (not the deprecated cloudrun v1 IamMember)
        gcp.cloudrunv2.ServiceIamMember(
            resource_id,
            project  = project,
            location = region,
            name     = svc_name,
            role     = role,
            member   = member,
        )

    elif resource_type == "gcs_bucket":
        bucket_name = outputs.get("name", "")
        if not bucket_name:
            logger.warning("IamBindingNode %s: missing 'name' from GcsBucketNode outputs", resource_id)
            return
        gcp.storage.BucketIAMMember(
            resource_id,
            bucket = bucket_name,
            role   = role,
            member = member,
        )

    elif resource_type == "workflow":
        # pulumi_gcp has no WorkflowIamMember — fall back to project level
        logger.warning(
            "IamBindingNode %s: pulumi_gcp has no WorkflowIamMember — "
            "falling back to project-level IAMMember for role '%s'",
            resource_id, role,
        )
        gcp.projects.IAMMember(resource_id, project=project, role=role, member=member)

    elif resource_type == "cloud_tasks_queue":
        queue_name = outputs.get("queue_name", "")
        if not queue_name:
            logger.warning("IamBindingNode %s: missing 'queue_name' from CloudTasksQueueNode outputs", resource_id)
            return
        gcp.cloudtasks.QueueIamMember(
            resource_id,
            project  = project,
            location = region,
            name     = queue_name,
            role     = role,
            member   = member,
        )

    elif resource_type == "cloud_function":
        fn_name = outputs.get("name", "")
        if not fn_name:
            logger.warning("IamBindingNode %s: missing 'name' from CloudFunctionsNode outputs", resource_id)
            return
        gcp.cloudfunctions.FunctionIamMember(
            resource_id,
            project        = project,
            region         = region,
            cloud_function = fn_name,
            role           = role,
            member         = member,
        )

    elif resource_type == "pubsub_subscription":
        sub_name = outputs.get("name", "")
        if not sub_name:
            logger.warning("IamBindingNode %s: missing 'name' from PubsubSubscriptionNode outputs", resource_id)
            return
        gcp.pubsub.SubscriptionIAMMember(
            resource_id,
            project      = project,
            subscription = sub_name,
            role         = role,
            member       = member,
        )

    elif resource_type == "pubsub_topic":
        topic_name = outputs.get("name", "")
        if not topic_name:
            logger.warning("IamBindingNode %s: missing 'name' from PubsubTopicNode outputs", resource_id)
            return
        gcp.pubsub.TopicIAMMember(
            resource_id,
            project = project,
            topic   = topic_name,
            role    = role,
            member  = member,
        )

    elif resource_type == "eventarc_trigger":
        # pulumi_gcp has no TriggerIamMember — fall back to project level
        logger.warning(
            "IamBindingNode %s: pulumi_gcp has no TriggerIamMember — "
            "falling back to project-level IAMMember for role '%s'",
            resource_id, role,
        )
        gcp.projects.IAMMember(resource_id, project=project, role=role, member=member)

    else:
        logger.warning(
            "IamBindingNode %s: unknown resource_type '%s' — falling back to project-level binding",
            resource_id, resource_type,
        )
        gcp.projects.IAMMember(resource_id, project=project, role=role, member=member)