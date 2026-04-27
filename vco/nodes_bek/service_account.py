"""
nodes/service_account.py — Service Account resource node (fully self-describing).

Topology
--------
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudRunNode

The node can either *create* a new SA in the workload project, or act as a
*reference* to an existing SA (possibly in a different project).

Set `create_sa = True`  → Pulumi creates the SA and exports its email.
Set `create_sa = False` → No resource is created; `email` is used as-is.
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


@dataclass
class ServiceAccountNode(GCPNode):
    """
    Service Account node.

    When wired into a CloudRunNode the CR will run under this SA instead of
    the default compute SA.

    Parameters
    ----------
    account_id  : short SA id  (e.g. "my-cr-runner") — used when create_sa=True
    email       : full SA email — used when create_sa=False (reference mode)
    display_name: human-readable name shown in GCP console
    create_sa   : True → create the SA; False → reference an existing one
    """

    params_schema: ClassVar = [
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
            "key":         "create_sa",
            "label":       "Create SA (uncheck to reference existing)",
            "type":        "boolean",
            "default":     True,
        },
    ]

    inputs:  ClassVar = []
    outputs: ClassVar = [Port("service_account", PortType.SERVICE_ACCOUNT, multi=True)]

    node_color:  ClassVar = "#a78bfa"
    icon:        ClassVar = "identity_and_access_management"
    category:    ClassVar = "IAM"
    description: ClassVar = "Service Account — create or reference for workload identity"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ServiceAccountNode → CloudRunNode  (or any node with a service_account input)
        if src_id == self.node_id and src_type == "ServiceAccountNode":
            ctx[tgt_id]["service_account_id"] = self.node_id
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        create_sa    = props.get("create_sa", True)
        account_id   = props.get("account_id", "").strip()
        display_name = props.get("display_name", account_id)
        ref_email    = props.get("email", "").strip()

        def program() -> None:
            if create_sa:
                if not account_id:
                    raise ValueError(
                        f"ServiceAccountNode {self.node_id}: 'account_id' is required when create_sa=True"
                    )
                sa = gcp.serviceaccount.Account(
                    self.node_id,
                    account_id=account_id,
                    display_name=display_name or account_id,
                    project=project,
                )
                pulumi.export("email",      sa.email)
                pulumi.export("account_id", sa.account_id)
                pulumi.export("id",         sa.id)
            else:
                # Reference mode — just re-export the email so downstream nodes
                # (CloudRun) can pick it up from deployed_outputs consistently.
                if not ref_email:
                    logger.warning(
                        "ServiceAccountNode %s: create_sa=False but no email provided",
                        self.node_id,
                    )
                pulumi.export("email",      ref_email)
                pulumi.export("account_id", ref_email.split("@")[0] if ref_email else "")

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"email": pulumi_outputs.get("email", "")}

    def log_source(self, pulumi_outputs, project, region):
        return None