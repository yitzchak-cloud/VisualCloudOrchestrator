"""
nodes/cloud_run_job.py — Cloud Run Job resource node (fully self-describing).

Cloud Run Jobs vs Cloud Run Services
-------------------------------------
  Service  — long-running HTTP server, always listening, scales to handle requests.
  Job      — runs to completion, no HTTP server required, triggered on demand or on schedule.

Topology
--------
  CloudSchedulerNode ──(RUN_JOB)──► CloudRunJobNode
  CloudRunJobNode    ──(STORAGE)──► GcsBucketNode   (env var injection)
  CloudRunJobNode    ──(TOPIC)────► PubsubTopicNode  (env var injection)
  ServiceAccountNode ──(SA)───────► CloudRunJobNode

The Job does NOT expose an HTTP port — Scheduler triggers it via the
Cloud Run Jobs API (not HTTP), so no ingress/VPC config is required for
the trigger path. VPC egress is still supported if the job needs to reach
private resources.

Exports
-------
  job_name  — short name of the created Job resource
  job_id    — fully-qualified resource id
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
import re
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class CloudRunJobNode(GCPNode):
    """
    Cloud Run Job — run-to-completion container workload.

    Connect CloudSchedulerNode → this node to trigger it on a cron schedule.
    Connect ServiceAccountNode → this node to run under a specific identity.
    Connect GcsBucketNode      ← this node to get GCS_BUCKET_* env vars.
    Connect PubsubTopicNode    ← this node to get PUBSUB_TOPIC_* env vars.
    """

    params_schema: ClassVar = [
        {
            "key": "name", "label": "Job Name",
            "type": "text", "default": "", "placeholder": "my-batch-job",
        },
        {
            "key": "image", "label": "Container Image",
            "type": "text", "default": "", "placeholder": "gcr.io/project/image:tag",
        },
        {
            "key": "memory", "label": "Memory",
            "type": "select",
            "options": ["256Mi", "512Mi", "1Gi", "2Gi", "4Gi", "8Gi"],
            "default": "512Mi",
        },
        {
            "key": "cpu", "label": "CPU",
            "type": "select", "options": ["1", "2", "4", "8"],
            "default": "1",
        },
        {
            "key": "parallelism", "label": "Parallelism (concurrent tasks)",
            "type": "number", "default": 1,
        },
        {
            "key": "task_count", "label": "Task Count",
            "type": "number", "default": 1,
        },
        {
            "key": "max_retries", "label": "Max Retries per Task",
            "type": "number", "default": 3,
        },
        {
            "key": "timeout", "label": "Task Timeout (seconds)",
            "type": "number", "default": 600,
        },
        {
            "key": "region", "label": "Region",
            "type": "select",
            "options": ["me-west1", "us-central1", "us-east1", "europe-west1"],
            "default": "me-west1",
        },
        # VPC egress (optional — for jobs that need private network access)
        {
            "key": "vpc_network", "label": "VPC Network (optional egress)",
            "type": "text", "default": "",
            "placeholder": "projects/HOST_PROJECT/global/networks/NETWORK",
        },
        {
            "key": "vpc_subnetwork", "label": "VPC Subnetwork (optional egress)",
            "type": "text", "default": "",
            "placeholder": "projects/HOST_PROJECT/regions/REGION/subnetworks/SUBNET",
        },
    ]

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
        Port("subnet",          PortType.NETWORK,          required=False),
        Port("triggered_by",    PortType.RUN_JOB,          required=False, multi=True, multi_in=True),
        Port("secret",          PortType.SECRET,            multi=True,     multi_in=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to", PortType.TOPIC,   multi=True),
        Port("writes_to",    PortType.STORAGE, multi=True),
    ]

    node_color:  ClassVar = "#818cf8"
    icon:        ClassVar = "cloudRunJob"
    category:    ClassVar = "Compute"
    description: ClassVar = "Run-to-completion container job"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and src_type == "CloudRunJobNode":
            if tgt_type == "PubsubTopicNode":
                ctx[self.node_id].setdefault("publishes_to_topics", []).append(tgt_id)
                return True
            if tgt_type == "GcsBucketNode":
                ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
                ctx[self.node_id].setdefault("bucket_ids", []).append(tgt_id)
                return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps  = list(ctx.get("publishes_to_topics", []))
        deps += ctx.get("bucket_ids", [])
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

        # ── VPC egress (optional) ─────────────────────────────────────────────
        subnet_id       = ctx.get("subnetwork_id", "")
        subnet_outputs  = deployed_outputs.get(subnet_id, {})
        network_path    = subnet_outputs.get("network_path")    or props.get("vpc_network",    "")
        subnetwork_path = subnet_outputs.get("subnetwork_path") or props.get("vpc_subnetwork", "")

        # ── Service Account ───────────────────────────────────────────────────
        sa_email = deployed_outputs.get(ctx.get("service_account_id", ""), {}).get("email", "")

        # ── Env vars from wired outputs ───────────────────────────────────────
        topic_envs = [
            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                name="PUBSUB_TOPIC_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, tid).upper()),
                value=deployed_outputs.get(tid, {}).get("name", ""),
            )
            for tid in ctx.get("publishes_to_topics", [])
        ]
        bucket_envs = [
            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                name="GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()),
                value=deployed_outputs.get(bid, {}).get("name", ""),
            )
            for bid in ctx.get("bucket_ids", [])
        ]
        all_envs = topic_envs + bucket_envs

        def program() -> None:
            job_name    = props.get("name") or _resource_name(node_dict)
            image       = props.get("image", "gcr.io/cloudrun/hello")
            memory      = props.get("memory", "512Mi")
            cpu         = props.get("cpu", "1")
            parallelism = int(props.get("parallelism", 1))
            task_count  = int(props.get("task_count", 1))
            max_retries = int(props.get("max_retries", 3))
            timeout_s   = int(props.get("timeout", 600))
            job_region  = props.get("region", region)

            # ── VPC access block (egress only) ────────────────────────────────
            vpc_access = None
            if network_path and subnetwork_path:
                vpc_access = gcp.cloudrunv2.JobTemplateTemplateVpcAccessArgs(
                    egress="PRIVATE_RANGES_ONLY",
                    network_interfaces=[
                        gcp.cloudrunv2.JobTemplateTemplateVpcAccessNetworkInterfaceArgs(
                            network=network_path,
                            subnetwork=subnetwork_path,
                        )
                    ],
                )

            j = gcp.cloudrunv2.Job(
                self.node_id,
                name=job_name,
                location=job_region,
                project=project,
                deletion_protection=False,
                template=gcp.cloudrunv2.JobTemplateArgs(
                    parallelism=parallelism,
                    task_count=task_count,
                    template=gcp.cloudrunv2.JobTemplateTemplateArgs(
                        service_account=sa_email or None,
                        max_retries=max_retries,
                        timeout=f"{timeout_s}s",
                        containers=[
                            gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                                image=image,
                                resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                                    limits={"memory": memory, "cpu": cpu},
                                ),
                                envs=all_envs or None,
                            )
                        ],
                        vpc_access=vpc_access,
                    ),
                ),
            )

            pulumi.export("job_name", j.name)
            pulumi.export("job_id",   j.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"name": pulumi_outputs.get("job_name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("job_name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="cloud_run_job"'
                f' AND resource.labels.job_name="{name}"'
                f' AND resource.labels.location="{region}"'
            ),
            project=project,
        )