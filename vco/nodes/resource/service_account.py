"""
nodes/service_account.py — Service Account resource node (fully self-describing).

Topology
--------
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudRunNode
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudSchedulerNode
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► EventarcTriggerNode
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudTasksQueueNode
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► WorkflowNode

IAM Roles
---------
This node can attach IAM bindings directly — no separate IamBindingNode needed
for simple cases.  Two categories of bindings are supported:

  project_roles  (list[str])
      Roles granted at project level, e.g.:
        - roles/datastore.user
        - roles/cloudtasks.enqueuer
        - roles/logging.logWriter
        - roles/workflows.invoker
        - roles/eventarc.eventReceiver
        - roles/iam.serviceAccountUser

      Equivalent gcloud command:
        gcloud projects add-iam-policy-binding ${PROJECT} \\
          --member="serviceAccount:${SA_EMAIL}" \\
          --role="roles/..."

  resource_bindings  (list[dict])
      Roles granted on a specific GCP resource (resource-scoped).
      Each dict has the shape:
        {
          "resource_type": "cloud_run_service" | "cloud_function" | "workflow" | "cloud_tasks_queue",
          "resource_ref":  "<node_id of the target resource node>",
          "role":          "roles/run.invoker" | "roles/run.viewer" | "roles/cloudfunctions.invoker" | ...
        }

      Equivalent gcloud command:
        gcloud run services add-iam-policy-binding ${SERVICE} \\
          --region=${REGION} \\
          --member="serviceAccount:${SA_EMAIL}" \\
          --role="roles/run.invoker"

      Supported resource_type values and their Pulumi binding resource:
        cloud_run_service   → gcp.cloudrun.IamMember  (region-scoped)
        cloud_function      → gcp.cloudfunctions.FunctionIamMember
        workflow            → gcp.projects.IAMMember  (project-level fallback; pulumi_gcp has no WorkflowIamMember)
        cloud_tasks_queue   → gcp.cloudtasks.QueueIamMember

Implementation note
-------------------
  Both project_roles and resource_bindings are created inside this node's
  pulumi_program so that:
    1. The SA itself is deployed first.
    2. Project bindings are attached immediately after SA creation.
    3. Resource bindings depend on deployed_outputs of the target node
       (they need the resource name/id), so dag_deps returns all target node ids.

  dag_deps therefore returns every node referenced in resource_bindings.

Parameters (params_schema)
--------------------------
  account_id       text    Short SA id used when create_sa=True
  display_name     text    Human-readable name
  email            text    Full SA email used when create_sa=False (reference mode)
  create_sa        bool    True → create; False → reference existing
  project_roles    text    Newline-separated list of project-level roles
  resource_bindings json   JSON array of resource-binding dicts (see above)

Exports
-------
  email       — full service account email
  account_id  — short account_id portion
  id          — full resource id (create mode only)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, Port, _resource_name, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# ── Supported resource-scoped binding types ───────────────────────────────────

_RESOURCE_BINDING_TYPES = [
    "cloud_run_service",
    "cloud_function",
    "workflow",
    "cloud_tasks_queue",
]

_RESOURCE_BINDING_ROLES = {
    "cloud_run_service": [
        "roles/run.invoker",
        "roles/run.viewer",
        "roles/run.admin",
    ],
    "cloud_function": [
        "roles/cloudfunctions.invoker",
        "roles/cloudfunctions.viewer",
    ],
    "workflow": [
        "roles/workflows.invoker",
        "roles/workflows.viewer",
    ],
    "cloud_tasks_queue": [
        "roles/cloudtasks.enqueuer",
        "roles/cloudtasks.viewer",
    ],
}

# Common project-level roles shown as suggestions in the UI textarea
_PROJECT_ROLE_SUGGESTIONS = "\n".join([
    "# Project-level roles — one per line",
    "# roles/datastore.user",
    "# roles/cloudtasks.enqueuer",
    "# roles/logging.logWriter",
    "# roles/workflows.invoker",
    "# roles/eventarc.eventReceiver",
    "# roles/iam.serviceAccountUser",
    "# roles/pubsub.publisher",
    "# roles/storage.objectCreator",
])


@dataclass
class ServiceAccountNode(GCPNode):
    """
    Service Account node — create or reference, with inline IAM role grants.

    Connect to any node with a SERVICE_ACCOUNT input port → that resource runs
    under this SA identity.

    IAM bindings can be configured directly on this node:

      project_roles      — roles at project level (e.g. roles/logging.logWriter)
      resource_bindings  — JSON array for resource-scoped bindings
                           (e.g. roles/run.invoker on a specific Cloud Run service)

    Both categories of bindings map 1-to-1 to the two gcloud idioms:

      gcloud projects add-iam-policy-binding ...   → project_roles
      gcloud run services add-iam-policy-binding ... → resource_bindings (cloud_run_service)
      gcloud functions add-iam-policy-binding ...   → resource_bindings (cloud_function)
    """

    params_schema: ClassVar = [
        # ── Identity ──────────────────────────────────────────────────────
        {
            "key":         "account_id",
            "label":       "Account ID",
            "type":        "text",
            "default":     "",
            "placeholder": "my-service-runner",
        },
        {
            "key":         "display_name",
            "label":       "Display Name",
            "type":        "text",
            "default":     "",
            "placeholder": "My Service Runner SA",
        },
        {
            "key":         "email",
            "label":       "Existing SA Email (reference mode)",
            "type":        "text",
            "default":     "",
            "placeholder": "sa@project.iam.gserviceaccount.com",
        },
        {
            "key":     "create_sa",
            "label":   "Create SA (uncheck to reference existing)",
            "type":    "checkbox",
            "default": True,
        },
        # ── Project-level roles ───────────────────────────────────────────
        {
            "key":         "project_roles",
            "label":       "Project-Level Roles (one per line)",
            "type":        "textarea",
            "default":     "",
            "placeholder": "roles/logging.logWriter\nroles/datastore.user",
        },
        # ── Resource-scoped bindings ──────────────────────────────────────
        # JSON array — each element:
        # {
        #   "resource_type": "cloud_run_service",
        #   "resource_ref":  "<node_id>",
        #   "role":          "roles/run.invoker"
        # }
        {
            "key":         "resource_bindings",
            "label":       "Resource-Level Bindings (JSON)",
            "type":        "json",
            "default":     "[]",
            "placeholder": (
                '[\n'
                '  {\n'
                '    "resource_type": "cloud_run_service",\n'
                '    "resource_ref":  "<node_id>",\n'
                '    "role":          "roles/run.invoker"\n'
                '  }\n'
                ']'
            ),
        },
    ]

    inputs:  ClassVar = []
    outputs: ClassVar = [Port("service_account", PortType.SERVICE_ACCOUNT, multi=True)]

    node_color:  ClassVar = "#a78bfa"
    icon:        ClassVar = "identity_and_access_management"
    category:    ClassVar = "IAM"
    description: ClassVar = (
        "Service Account — create or reference; attach project-level and "
        "resource-level IAM bindings inline."
    )

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        """
        When this SA is wired into any node, record service_account_id on the
        target so the target's pulumi_program can pick up the SA email.
        """
        if src_id == self.node_id and src_type == "ServiceAccountNode":
            ctx[tgt_id]["service_account_id"] = self.node_id
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        """
        Resource bindings depend on the target resource being deployed first
        (we need its resource name / id from deployed_outputs).
        """
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        bindings  = _parse_resource_bindings(props.get("resource_bindings", "[]"))
        return [b["resource_ref"] for b in bindings if b.get("resource_ref")]

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

        create_sa    = props.get("create_sa", True)
        account_id   = props.get("account_id", "").strip()
        display_name = props.get("display_name", account_id)
        ref_email    = props.get("email", "").strip()

        # ── Parse role lists ──────────────────────────────────────────────
        raw_roles    = props.get("project_roles", "")
        project_roles = _parse_project_roles(raw_roles)
        resource_bindings = _parse_resource_bindings(props.get("resource_bindings", "[]"))

        def program() -> None:
            # ── 1. Create or reference the SA ─────────────────────────────
            if create_sa:
                if not account_id:
                    raise ValueError(
                        f"ServiceAccountNode {self.node_id}: "
                        "'account_id' is required when create_sa=True"
                    )
                sa = gcp.serviceaccount.Account(
                    self.node_id,
                    account_id=account_id,
                    display_name=display_name or account_id,
                    project=project,
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

            member = sa_email.apply(lambda e: f"serviceAccount:{e}") if create_sa \
                     else f"serviceAccount:{sa_email}"

            # ── 2. Project-level bindings ─────────────────────────────────
            # Equivalent: gcloud projects add-iam-policy-binding ${PROJECT} \
            #   --member="serviceAccount:${SA_EMAIL}" --role="roles/..."
            for idx, role in enumerate(project_roles):
                gcp.projects.IAMMember(
                    f"{self.node_id}-proj-{idx}",
                    project=project,
                    role=role,
                    member=member,
                )
                logger.info("ServiceAccountNode %s: project binding %s", self.node_id, role)

            # ── 3. Resource-level bindings ────────────────────────────────
            for idx, binding in enumerate(resource_bindings):
                rtype   = binding.get("resource_type", "")
                ref_id  = binding.get("resource_ref",  "")
                role    = binding.get("role",           "")
                outputs = deployed_outputs.get(ref_id, {})

                if not rtype or not role:
                    logger.warning(
                        "ServiceAccountNode %s: incomplete resource binding at index %d — skip",
                        self.node_id, idx,
                    )
                    continue

                _create_resource_binding(
                    resource_id   = f"{self.node_id}-res-{idx}",
                    resource_type = rtype,
                    role          = role,
                    member        = member,
                    outputs       = outputs,
                    project       = project,
                    region        = region,
                )

        return program

    # ------------------------------------------------------------------
    # Post-deploy
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"email": pulumi_outputs.get("email", "")}

    def log_source(self, pulumi_outputs, project, region):
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_project_roles(raw: str) -> list[str]:
    """
    Parse the textarea value into a clean list of role strings.
    Ignores blank lines and comment lines (starting with #).
    """
    roles = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        roles.append(line)
    return roles


def _parse_resource_bindings(raw: str | list) -> list[dict]:
    """
    Parse the JSON textarea value into a list of binding dicts.
    Returns [] on any parse error.
    """
    if isinstance(raw, list):
        return raw
    if not raw or not raw.strip():
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


def _create_resource_binding(
    resource_id:   str,
    resource_type: str,
    role:          str,
    member:        Any,       # str or Pulumi Output[str]
    outputs:       dict,
    project:       str,
    region:        str,
) -> None:
    """
    Create the appropriate Pulumi IAM resource for a resource-scoped binding.

    resource_type → Pulumi resource      → equivalent gcloud command
    ─────────────────────────────────────────────────────────────────
    cloud_run_service  gcp.cloudrun.IamMember
        gcloud run services add-iam-policy-binding SERVICE \\
          --region=REGION --member=... --role=...

    cloud_function     gcp.cloudfunctions.FunctionIamMember
        gcloud functions add-iam-policy-binding FUNCTION \\
          --member=... --role=...

    workflow           gcp.projects.IAMMember  (project-level fallback)
        gcloud projects add-iam-policy-binding ${PROJECT} \
          --member=... --role=roles/workflows.invoker

    cloud_tasks_queue  gcp.cloudtasks.QueueIamMember
        (no direct gcloud equivalent — resource binding via API)
    """
    if resource_type == "cloud_run_service":
        svc_name = outputs.get("name", "")
        if not svc_name:
            logger.warning("IAM binding %s: no 'name' export from cloud_run_service — skip", resource_id)
            return
        # Equivalent:
        #   gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
        #     --region=${REGION} \
        #     --member="serviceAccount:${SA_EMAIL}" \
        #     --role="roles/run.invoker"
        gcp.cloudrun.IamMember(
            resource_id,
            location=region,
            project=project,
            service=svc_name,
            role=role,
            member=member,
        )

    elif resource_type == "cloud_function":
        fn_name = outputs.get("name", "")
        if not fn_name:
            logger.warning("IAM binding %s: no 'name' export from cloud_function — skip", resource_id)
            return
        # Equivalent:
        #   gcloud functions add-iam-policy-binding ${FUNCTION_NAME} \
        #     --member="serviceAccount:${SA_EMAIL}" \
        #     --role="roles/cloudfunctions.invoker"
        gcp.cloudfunctions.FunctionIamMember(
            resource_id,
            project=project,
            region=region,
            cloud_function=fn_name,
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
            "IAM binding %s: pulumi_gcp has no WorkflowIamMember — "
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
            logger.warning("IAM binding %s: no 'queue_name' export from cloud_tasks_queue — skip", resource_id)
            return
        gcp.cloudtasks.QueueIamMember(
            resource_id,
            project=project,
            location=region,
            name=queue_name,
            role=role,
            member=member,
        )

    else:
        logger.warning(
            "IAM binding %s: unsupported resource_type '%s' — skip",
            resource_id, resource_type,
        )