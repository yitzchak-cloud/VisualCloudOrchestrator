"""
nodes/resource/service_account/service_account.py
──────────────────────────────────────────────────────────────────────────────
ServiceAccountNode — create or reference a GCP Service Account, with inline
project-level and resource-level IAM bindings.

Terraform output
----------------
  create_sa=True   → google_service_account
  create_sa=False  → no resource (reference only, bindings still applied)

  Project-level IAM bindings (project_roles)
    → google_project_iam_member  (one per role)

  Resource-scoped bindings (resource_bindings JSON)
    cloud_run_service  → google_cloud_run_v2_service_iam_member
    cloud_function     → google_cloudfunctions_function_iam_member
    workflow           → google_project_iam_member  (project-level fallback)
    cloud_tasks_queue  → google_cloud_tasks_queue_iam_member

What changed vs previous version
─────────────────────────────────
* params_schema moved to service_account_params.yaml (categories + descriptions).
* Pulumi cloud_run_service binding uses gcp.cloudrunv2.ServiceIamMember (not v1).
* terraform_dir removed — path convention follows node directory standard.
* terraform_call_vars now includes resource_bindings serialised for the module.
* _append_tf_resource_binding: location/region hardcoded strings → "var.region".
* terraform/variables.tf, main.tf, outputs.tf added.
"""
from __future__ import annotations

import json
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

_RESOURCE_BINDING_TYPES = [
    "cloud_run_service",
    "cloud_function",
    "workflow",
    "cloud_tasks_queue",
]


@dataclass
class ServiceAccountNode(GCPNode):
    """
    Service Account node — create or reference, with inline IAM role grants.

    create_sa=True  → creates google_service_account + all IAM bindings.
    create_sa=False → references an existing SA by email; bindings still applied.

    Wire the output port to any node that accepts a SERVICE_ACCOUNT input
    (CloudRunNode, IamBindingNode, etc.) to propagate the SA email.
    """

    # params loaded from service_account_params.yaml automatically by base_node

    inputs:  ClassVar = []
    outputs: ClassVar = [Port("service_account", PortType.SERVICE_ACCOUNT, multi=True)]

    node_color:  ClassVar = "#a78bfa"
    icon:        ClassVar = "identity_and_access_management"
    category:    ClassVar = "IAM"
    description: ClassVar = (
        "Service Account — create or reference; attach project-level and "
        "resource-level IAM bindings inline."
    )

    # ──────────────────────────────────────────────────────────────────────────
    # Edge wiring
    # ──────────────────────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and src_type == "ServiceAccountNode":
            ctx[tgt_id]["service_account_id"] = self.node_id
            return True
        return False

    # ──────────────────────────────────────────────────────────────────────────
    # DAG dependencies
    # ──────────────────────────────────────────────────────────────────────────

    def dag_deps(self, ctx) -> list[str]:
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        bindings  = _parse_resource_bindings(props.get("resource_bindings", "[]"))
        return [b["resource_ref"] for b in bindings if b.get("resource_ref")]

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

        create_sa    = props.get("create_sa", True)
        account_id   = props.get("account_id", "").strip()
        display_name = props.get("display_name", account_id)
        ref_email    = props.get("email", "").strip()

        project_roles     = _parse_project_roles(props.get("project_roles", ""))
        resource_bindings = _parse_resource_bindings(props.get("resource_bindings", "[]"))

        def program() -> None:
            if create_sa:
                if not account_id:
                    raise ValueError(
                        f"ServiceAccountNode {self.node_id}: "
                        "'account_id' is required when create_sa=True"
                    )
                sa = gcp.serviceaccount.Account(
                    self.node_id,
                    account_id   = account_id,
                    display_name = display_name or account_id,
                    project      = project,
                )
                sa_email = sa.email
                pulumi.export("email",      sa.email)
                pulumi.export("account_id", sa.account_id)
                pulumi.export("id",         sa.id)
            else:
                if not ref_email:
                    logger.warning(
                        "ServiceAccountNode %s: create_sa=False but no email provided",
                        self.node_id,
                    )
                sa_email = ref_email
                pulumi.export("email",      ref_email)
                pulumi.export("account_id", ref_email.split("@")[0] if ref_email else "")

            # member string — Output[str] when created, plain str when referenced
            member = (
                sa_email.apply(lambda e: f"serviceAccount:{e}")
                if create_sa
                else f"serviceAccount:{sa_email}"
            )

            # Project-level bindings
            for idx, role in enumerate(project_roles):
                gcp.projects.IAMMember(
                    f"{self.node_id}-proj-{idx}",
                    project = project,
                    role    = role,
                    member  = member,
                )

            # Resource-level bindings
            for idx, binding in enumerate(resource_bindings):
                rtype  = binding.get("resource_type", "")
                ref_id = binding.get("resource_ref",  "")
                role   = binding.get("role",           "")
                outputs = deployed_outputs.get(ref_id, {})

                if not rtype or not role:
                    continue

                _create_pulumi_resource_binding(
                    resource_id   = f"{self.node_id}-res-{idx}",
                    resource_type = rtype,
                    role          = role,
                    member        = member,
                    outputs       = outputs,
                    project       = project,
                    region        = region,
                )

        return program

    # ──────────────────────────────────────────────────────────────────────────
    # Terraform — inline blocks
    # ──────────────────────────────────────────────────────────────────────────

    def terraform_blocks(self, ctx, project, region, all_nodes) -> TFResult:
        result    = TFResult()
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        create_sa    = props.get("create_sa", True)
        account_id   = props.get("account_id", _resource_name(node_dict)).strip()
        display_name = props.get("display_name", node_dict.get("label", account_id))
        ref_email    = props.get("email", "").strip()
        tf_id        = _tf_name(node_dict)

        project_roles     = _parse_project_roles(props.get("project_roles", ""))
        resource_bindings = _parse_resource_bindings(props.get("resource_bindings", "[]"))

        # ── 1. Service Account resource ───────────────────────────────────────
        if create_sa:
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_service_account", tf_id],
                body={
                    "account_id":   account_id,
                    "display_name": display_name,
                    "project":      "var.project_id",
                },
                comment=f"Service Account: {node_dict.get('label', account_id)}",
            ))
            sa_email_ref = f"${{google_service_account.{tf_id}.email}}"
            member_ref   = f"serviceAccount:${{google_service_account.{tf_id}.email}}"
        else:
            sa_email_ref = ref_email
            member_ref   = f"serviceAccount:{ref_email}"

        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_email"],
            body={
                "description": f"Email of service account {account_id}",
                "value":       sa_email_ref,
            },
        ))

        # ── 2. Project-level IAM bindings ─────────────────────────────────────
        for idx, role in enumerate(project_roles):
            safe_role = role.replace("/", "_").replace(".", "_")
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_project_iam_member", f"{tf_id}_proj_{safe_role}"],
                body={
                    "project": "var.project_id",
                    "role":    role,
                    "member":  member_ref,
                },
                comment=f"Project IAM: {role}",
            ))

        # ── 3. Resource-scoped IAM bindings ───────────────────────────────────
        for idx, binding in enumerate(resource_bindings):
            rtype  = binding.get("resource_type", "")
            ref_id = binding.get("resource_ref",  "")
            role   = binding.get("role",           "")

            if not rtype or not role:
                continue

            target_node = _node_by_id(all_nodes, ref_id) if ref_id else {}
            target_tf   = _tf_name(target_node) if target_node else ""

            _append_tf_resource_binding(
                result      = result,
                resource_id = f"{tf_id}_res_{idx}",
                rtype       = rtype,
                role        = role,
                member_ref  = member_ref,
                target_tf   = target_tf,
            )

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Terraform — static module interface
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return "sa"

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        roles     = _parse_project_roles(props.get("project_roles", ""))
        roles_hcl = "[" + ", ".join(f'"{r}"' for r in roles) + "]"

        # Serialise resource_bindings for the TF module as a JSON string variable
        bindings     = _parse_resource_bindings(props.get("resource_bindings", "[]"))
        bindings_hcl = json.dumps(bindings)   # module receives as jsonencode-compatible string

        cv: dict[str, str] = {
            "account_id":        f'"{props.get("account_id") or _resource_name(node_dict)}"',
            "display_name":      f'"{props.get("display_name") or node_dict.get("label", "")}"',
            "create_sa":         "false" if not props.get("create_sa", True) else "true",
            "project_roles":     roles_hcl,
            "resource_bindings": f'"{bindings_hcl}"',
        }

        if not props.get("create_sa", True) and props.get("email"):
            cv["existing_email"] = f'"{props["email"]}"'

        return cv

    # ──────────────────────────────────────────────────────────────────────────
    # Post-deploy
    # ──────────────────────────────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"email": pulumi_outputs.get("email", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return None


# ── Pulumi IAM helper ─────────────────────────────────────────────────────────

def _create_pulumi_resource_binding(
    resource_id:   str,
    resource_type: str,
    role:          str,
    member:        Any,
    outputs:       dict,
    project:       str,
    region:        str,
) -> None:
    """
    Create a Pulumi IAM member resource for a specific GCP resource type.

      cloud_run_service  → gcp.cloudrunv2.ServiceIamMember   (v2, not v1)
      cloud_function     → gcp.cloudfunctions.FunctionIamMember
      workflow           → gcp.projects.IAMMember             (no SDK resource-level)
      cloud_tasks_queue  → gcp.cloudtasks.QueueIamMember
    """
    if resource_type == "cloud_run_service":
        svc_name = outputs.get("name", "")
        if not svc_name:
            logger.warning("IAM binding %s: no 'name' export from CloudRunNode — skip", resource_id)
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

    elif resource_type == "cloud_function":
        fn_name = outputs.get("name", "")
        if not fn_name:
            logger.warning("IAM binding %s: no 'name' export from CloudFunctionsNode — skip", resource_id)
            return
        gcp.cloudfunctions.FunctionIamMember(
            resource_id,
            project        = project,
            region         = region,
            cloud_function = fn_name,
            role           = role,
            member         = member,
        )

    elif resource_type == "workflow":
        logger.warning(
            "IAM binding %s: no WorkflowIamMember in pulumi_gcp — "
            "falling back to project-level IAMMember for role '%s'",
            resource_id, role,
        )
        gcp.projects.IAMMember(resource_id, project=project, role=role, member=member)

    elif resource_type == "cloud_tasks_queue":
        queue_name = outputs.get("queue_name", "")
        if not queue_name:
            logger.warning("IAM binding %s: no 'queue_name' export from CloudTasksQueueNode — skip", resource_id)
            return
        gcp.cloudtasks.QueueIamMember(
            resource_id,
            project  = project,
            location = region,
            name     = queue_name,
            role     = role,
            member   = member,
        )

    else:
        logger.warning(
            "IAM binding %s: unsupported resource_type '%s' — skip",
            resource_id, resource_type,
        )


# ── Terraform IAM helper ──────────────────────────────────────────────────────

def _append_tf_resource_binding(
    result:      TFResult,
    resource_id: str,
    rtype:       str,
    role:        str,
    member_ref:  str,
    target_tf:   str,
) -> None:
    """
    Append the appropriate google_*_iam_member TFBlock for a resource binding.
    Uses var.project_id and var.region throughout — never hardcoded strings.
    """
    if rtype == "cloud_run_service" and target_tf:
        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_run_v2_service_iam_member", resource_id],
            body={
                "project":  "var.project_id",
                "location": "var.region",
                "name":     f"${{google_cloud_run_v2_service.{target_tf}.name}}",
                "role":     role,
                "member":   member_ref,
            },
            comment=f"IAM: {role} on Cloud Run service",
        ))

    elif rtype == "cloud_function" and target_tf:
        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloudfunctions_function_iam_member", resource_id],
            body={
                "project":        "var.project_id",
                "region":         "var.region",
                "cloud_function": f"${{google_cloudfunctions_function.{target_tf}.name}}",
                "role":           role,
                "member":         member_ref,
            },
            comment=f"IAM: {role} on Cloud Function",
        ))

    elif rtype == "workflow":
        # No google_workflows_workflow_iam_member in Terraform provider → project-level fallback
        logger.warning(
            "_append_tf_resource_binding: 'workflow' has no resource-level TF IAM resource — "
            "falling back to google_project_iam_member for role '%s'",
            role,
        )
        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_project_iam_member", resource_id],
            body={
                "project": "var.project_id",
                "role":    role,
                "member":  member_ref,
            },
            comment=f"IAM: {role} (workflow — project-level fallback)",
        ))

    elif rtype == "cloud_tasks_queue" and target_tf:
        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_tasks_queue_iam_member", resource_id],
            body={
                "project":  "var.project_id",
                "location": "var.region",
                "name":     f"${{google_cloud_tasks_queue.{target_tf}.name}}",
                "role":     role,
                "member":   member_ref,
            },
            comment=f"IAM: {role} on Cloud Tasks queue",
        ))

    else:
        logger.warning(
            "_append_tf_resource_binding: unsupported rtype '%s' (target_tf='%s') — skip",
            rtype, target_tf,
        )


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _parse_project_roles(raw: str) -> list[str]:
    """Parse newline-separated role list, ignoring blank lines and # comments."""
    roles = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            roles.append(line)
    return roles


def _parse_resource_bindings(raw: str | list) -> list[dict]:
    """Parse JSON array of resource binding dicts; return [] on any error."""
    if isinstance(raw, list):
        return raw
    if not raw or not str(raw).strip():
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        logger.warning("resource_bindings: expected JSON array, got %s", type(parsed))
        return []
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.warning("resource_bindings: JSON parse error — %s", exc)
        return []
