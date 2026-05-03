"""
nodes/network.py — VPC Network and Subnetwork resource nodes (fully self-describing).

Topology
--------
  VpcNetworkNode  ──(NETWORK)──►  SubnetworkNode  ──(NETWORK)──►  CloudRunNode

The CloudRunNode reads vpc_access from whichever SubnetworkNode is wired into it.
A SubnetworkNode holds a reference to its parent VpcNetworkNode so that CloudRun
can reconstruct both the full network path and the full subnetwork path.

These nodes are *reference-only* — they describe an existing shared-VPC that lives
in a *host project* (often different from the workload project), so no Pulumi
resources are created; only the path strings are propagated via ctx/deployed_outputs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

import pulumi

from nodes.base_node import GCPNode, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

_DEFAULT_HOST_PROJECT = "hrz-endor-net-0"
_DEFAULT_NETWORK      = "endor-0"
_DEFAULT_SUBNETWORK   = "endor-1-subnet"
_DEFAULT_REGION       = "me-west1"


# ── VPC Network ───────────────────────────────────────────────────────────────

@dataclass
class VpcNetworkNode(GCPNode):
    """
    Reference node for a (shared-VPC) network.

    It does NOT create any GCP resource — it simply stores the host-project and
    network name so that attached SubnetworkNodes (and transitively CloudRun)
    can build the fully-qualified resource path:
        projects/<host_project>/global/networks/<network_name>
    """

    params_schema: ClassVar = [
        {
            "key":         "host_project",
            "label":       "Host Project",
            "type":        "text",
            "default":     _DEFAULT_HOST_PROJECT,
            "placeholder": "hrz-endor-net-0",
        },
        {
            "key":         "network_name",
            "label":       "Network Name",
            "type":        "text",
            "default":     _DEFAULT_NETWORK,
            "placeholder": "endor-0",
        },
    ]

    inputs:  ClassVar = []
    outputs: ClassVar = [Port("subnets", PortType.NETWORK, multi=True)]

    node_color:  ClassVar = "#34d399"
    icon:        ClassVar = "network"
    category:    ClassVar = "Networking"
    description: ClassVar = "Shared-VPC network reference (no resource created)"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # VpcNetworkNode → SubnetworkNode
        if src_id == self.node_id and src_type == "VpcNetworkNode" and tgt_type == "SubnetworkNode":
            # Tell the subnetwork who its parent network is
            ctx[tgt_id]["vpc_network_id"] = self.node_id
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # No Pulumi resource — just export the resolved path strings
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        host_project = props.get("host_project", _DEFAULT_HOST_PROJECT) or _DEFAULT_HOST_PROJECT
        network_name = props.get("network_name", _DEFAULT_NETWORK)      or _DEFAULT_NETWORK
        network_path = f"projects/{host_project}/global/networks/{network_name}"

        def program() -> None:
            pulumi.export("network_path", network_path)
            pulumi.export("host_project", host_project)
            pulumi.export("network_name", network_name)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "host_project": pulumi_outputs.get("host_project", ""),
            "network_name": pulumi_outputs.get("network_name", ""),
        }

    def log_source(self, pulumi_outputs, project, region):
        return None   # networks have no useful log stream


# ── Subnetwork ────────────────────────────────────────────────────────────────

@dataclass
class SubnetworkNode(GCPNode):
    """
    Reference node for a subnetwork inside a VpcNetworkNode.

    Connect:  VpcNetworkNode ──► SubnetworkNode ──► CloudRunNode

    SubnetworkNode inherits its host_project from the parent VpcNetworkNode
    (via ctx), so you only need to specify the subnetwork name and region here.

    The fully-qualified subnetwork path it produces:
        projects/<host_project>/regions/<region>/subnetworks/<subnetwork_name>
    """

    params_schema: ClassVar = [
        {
            "key":         "subnetwork_name",
            "label":       "Subnetwork Name",
            "type":        "text",
            "default":     _DEFAULT_SUBNETWORK,
            "placeholder": "endor-1-subnet",
        },
        {
            "key":         "region",
            "label":       "Region",
            "type":        "select",
            "options":     ["me-west1", "us-central1", "us-east1", "europe-west1"],
            "default":     _DEFAULT_REGION,
        },
    ]

    inputs:  ClassVar = [Port("network", PortType.NETWORK, required=True)]
    outputs: ClassVar = [Port("cloud_run", PortType.NETWORK, multi=True)]

    node_color:  ClassVar = "#6ee7b7"
    icon:        ClassVar = "subnet"
    category:    ClassVar = "Networking"
    description: ClassVar = "Shared-VPC subnetwork reference (no resource created)"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # SubnetworkNode → CloudRunNode
        if src_id == self.node_id and src_type == "SubnetworkNode" and tgt_type == "CloudRunNode":
            ctx[tgt_id]["subnetwork_id"] = self.node_id
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        # Must deploy (export) the parent VPC first so we can read network_path
        vpc_id = ctx.get("vpc_network_id")
        return [vpc_id] if vpc_id else []

    # ------------------------------------------------------------------
    # No Pulumi resource — export fully-qualified path strings
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        # Inherit host_project from parent VpcNetworkNode outputs
        vpc_id       = ctx.get("vpc_network_id", "")
        vpc_outputs  = deployed_outputs.get(vpc_id, {})
        host_project = vpc_outputs.get("host_project", _DEFAULT_HOST_PROJECT)
        network_path = vpc_outputs.get("network_path",
                       f"projects/{host_project}/global/networks/{_DEFAULT_NETWORK}")

        subnet_name   = props.get("subnetwork_name", _DEFAULT_SUBNETWORK) or _DEFAULT_SUBNETWORK
        subnet_region = props.get("region", region) or region
        subnet_path   = f"proj                                                                                                                                                                                                                                                                                                                                                                                                                                ects/{host_project}/regions/{subnet_region}/subnetworks/{subnet_name}"

        def program() -> None:
            pulumi.export("subnetwork_path", subnet_path)
            pulumi.export("network_path",    network_path)
            pulumi.export("subnetwork_name", subnet_name)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "subnetwork_name": pulumi_outputs.get("subnetwork_name", ""),
        }

    def log_source(self, pulumi_outputs, project, region):
        return None