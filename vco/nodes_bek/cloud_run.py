"""
nodes/cloud_run.py — Cloud Run resource nodes (fully self-describing).

VPC wiring
----------
  VpcNetworkNode ──► SubnetworkNode ──► CloudRunNode

Service-Account wiring
----------------------
  ServiceAccountNode ──► CloudRunNode

HTTP callers wiring
-------------------
  CloudSchedulerNode  ──(HTTP_TARGET)──► CloudRunNode
  EventarcTriggerNode ──(HTTP_TARGET)──► CloudRunNode
  WorkflowNode        ──(HTTP_TARGET)──► CloudRunNode
  CloudTasksQueueNode ──(TASK_QUEUE)───► CloudRunNode

  Every caller node that wires into CloudRunNode gets two env vars injected on
  its own side (handled in the caller's pulumi_program via deployed_outputs):
    CLOUD_RUN_URL_<SERVICE _NAME>  — the service URI
    CLOUD_RUN_NAME_<SERVICE_NAME> — the short service name

  On the CloudRun side we inject:
    SELF_URL  — this service's own URI (useful for self-referencing, health checks)

GCS writers wiring
------------------
  CloudRunNode ──(STORAGE)──► GcsBucketNode
  WorkflowNode ──(STORAGE)──► GcsBucketNode

  GcsBucketNode injects GCS_BUCKET_<NAME> into any wired writer node.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
import re
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_label, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# ── Cloud Run ─────────────────────────────────────────────────────────────────

@dataclass
class CloudRunNode(GCPNode):
    name:          str  = ""
    image:         str  = ""
    memory:        str  = "512Mi"
    region:        str  = "me-west1"
    cpu:           str  = "1"
    min_instances: int  = 0
    max_instances: int  = 10
    port:          int  = 8080   
    env_vars:      dict = field(default_factory=dict)
    service_url:   str  = ""

    params_schema: ClassVar = [
        {"key": "name",          "label": "Service Name",    "type": "text",   "default": "", "placeholder": "your-service-name"},
        {"key": "image",         "label": "Container Image", "type": "text",   "default": "", "placeholder": "gcr.io/project/image:tag"},
        {"key": "memory",        "label": "Memory",          "type": "select", "options": ["256Mi","512Mi","1Gi","2Gi","4Gi","8Gi"], "default": "512Mi"},
        {"key": "cpu",           "label": "CPU",             "type": "select", "options": ["1","2","4","8"], "default": "1"},
        {"key": "min_instances", "label": "Min Instances",   "type": "number", "default": 0},
        {"key": "max_instances", "label": "Max Instances",   "type": "number", "default": 10},
        {"key": "port",          "label": "Port",            "type": "number", "default": 8080},
        {"key": "region",        "label": "Region",          "type": "select", "options": ["me-west1","us-central1","us-east1"], "default": "me-west1"},
        {"key": "service_url",   "label": "Service URL",     "type": "text",   "default": "", "placeholder": "https://my-service.run.app"},
        {
            "key": "vpc_network", "label": "VPC Network (fallback)",
            "type": "text", "default": "",
            "placeholder": "projects/HOST_PROJECT/global/networks/NETWORK",
        },
        {
            "key": "vpc_subnetwork", "label": "VPC Subnetwork (fallback)",
            "type": "text", "default": "",
            "placeholder": "projects/HOST_PROJECT/regions/REGION/subnetworks/SUBNET",
        },
        # {"key": "workflow_yaml", "label": "Workflow Definition", "type": "yaml"},
        # {"key": "source_code",   "label": "Cloud Function Code", "type": "code", "language": "python"},
        # {"key": "config_json",   "label": "Config", "type": "json"},
    ]
    url_field: ClassVar = "service_url"

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
        Port("subnet",          PortType.NETWORK,          required=False),
        Port("http_callers",    PortType.HTTP_TARGET,      required=False, multi=True, multi_in=True),
        Port("task_queue",      PortType.TASK_QUEUE,       required=False, multi=True, multi_in=True),
        Port("secret",          PortType.SECRET,           multi=True,     multi_in=True),
        Port("MESSAGE",         PortType.MESSAGE,          multi=True,     multi_in=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to",    PortType.TOPIC,   multi=True),
        Port("writes_to",       PortType.STORAGE, multi=True),
    ]
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloudRun"
    category:    ClassVar = "Compute"
    description: ClassVar = "Serverless container runtime"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and src_type == "CloudRunNode":
            if tgt_type == "PubsubTopicNode":
                ctx[self.node_id].setdefault("publishes_to_topics", []).append(tgt_id)
                return True
            # CloudRunNode → GcsBucketNode: tell the bucket a writer is connected
            if tgt_type == "GcsBucketNode":
                ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
                return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = list(ctx.get("publishes_to_topics", []))
        deps += ctx.get("bucket_ids", [])        # buckets that inject env vars into this CR
        deps += ctx.get("task_queue_ids", [])    # queues that inject env vars into this CR
        if ctx.get("subnetwork_id"):
            deps.append(ctx["subnetwork_id"])
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        # ── VPC paths ─────────────────────────────────────────────────────────
        subnet_id       = ctx.get("subnetwork_id", "")
        subnet_outputs  = deployed_outputs.get(subnet_id, {})
        network_path    = subnet_outputs.get("network_path")    or props.get("vpc_network",    "")
        subnetwork_path = subnet_outputs.get("subnetwork_path") or props.get("vpc_subnetwork", "")

        if not network_path or not subnetwork_path:
            logger.warning(
                "CloudRunNode %s: no VPC network/subnetwork resolved — "
                "connect a SubnetworkNode or fill the fallback props",
                self.node_id,
            )

        # ── Service Account ───────────────────────────────────────────────────
        sa_email = deployed_outputs.get(ctx.get("service_account_id", ""), {}).get("email", "")

        # ── Pub/Sub env vars ──────────────────────────────────────────────────
        topic_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="PUBSUB_TOPIC_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, tid).upper()),
                value=deployed_outputs.get(tid, {}).get("name", ""),
            )
            for tid in ctx.get("publishes_to_topics", [])
        ]
        sub_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="PUBSUB_SUBSCRIPTION_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, sid).upper()),
                value=_resource_name(next((n for n in all_nodes if n["id"] == sid), {})),
            )
            for sid in ctx.get("receives_from_subs", [])
        ]

        # ── Bucket env vars (GcsBucketNode → CloudRunNode) ───────────────────
        # bucket_ids is populated by GcsBucketNode.resolve_edges when it wires
        # its STORAGE output into this CR.
        bucket_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()),
                value=deployed_outputs.get(bid, {}).get("name", ""),
            )
            for bid in ctx.get("bucket_ids", [])
        ]

        # ── Task queue env vars ───────────────────────────────────────────────
        queue_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="CLOUD_TASKS_QUEUE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, qid).upper()),
                value=deployed_outputs.get(qid, {}).get("queue_name", ""),
            )
            for qid in ctx.get("task_queue_ids", [])
        ]

        # NOTE: SELF_URL is added inside program() after svc is created,
        # because it's a Pulumi Output[str] — it cannot be resolved at
        # plan-time. We add it as a separate env var via apply().

        all_envs = topic_envs + sub_envs + bucket_envs + queue_envs

        def program() -> None:
            # ── VPC access block ──────────────────────────────────────────────
            vpc_access = None
            if network_path and subnetwork_path:
                vpc_access = gcp.cloudrunv2.ServiceTemplateVpcAccessArgs(
                    egress="PRIVATE_RANGES_ONLY",
                    network_interfaces=[
                        gcp.cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=network_path,
                            subnetwork=subnetwork_path,
                        )
                    ],
                )

            svc = gcp.cloudrunv2.Service(
                self.node_id,
                name=_resource_name(node_dict),
                location=region,
                project=project,
                deletion_protection=False,
                ingress="INGRESS_TRAFFIC_INTERNAL_ONLY",
                template=gcp.cloudrunv2.ServiceTemplateArgs(
                    service_account=sa_email or None,
                    containers=[gcp.cloudrunv2.ServiceTemplateContainerArgs(
                        image=props.get("image", "gcr.io/cloudrun/hello"),
                        # SELF_URL cannot be added here statically — callers
                        # (Scheduler, Eventarc, Workflows) read svc.uri from
                        # deployed_outputs and use it directly.
                        envs=all_envs or None,
                    )],
                    vpc_access=vpc_access,
                ),
            )
            pulumi.export("uri",  svc.uri)
            pulumi.export("name", svc.name)
            pulumi.export("id",   svc.id)

        return program

    # ------------------------------------------------------------------
    # Post-deploy
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"service_url": pulumi_outputs.get("uri", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="cloud_run_revision"'
                f' AND resource.labels.service_name="{name}"'
                f' AND resource.labels.location="{region}"'
            ),
            project=project,
        )