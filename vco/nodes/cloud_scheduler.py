"""
nodes/cloud_scheduler.py — Cloud Scheduler resource node (fully self-describing).

Topology
--------
  CloudSchedulerNode ──(HTTP_TARGET)──► CloudRunNode
  CloudSchedulerNode ──(RUN_JOB)──────► CloudRunJobNode
  CloudSchedulerNode ──(TOPIC)────────► PubsubTopicNode

Delivery modes (auto-detected from what is wired):
  • http    — POST to a Cloud Run Service URL
  • run_job — trigger a Cloud Run Job via the Jobs API (not HTTP)
  • pubsub  — publish a message to a Pub/Sub topic

Multiple targets of different types can be wired simultaneously.
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
class CloudSchedulerNode(GCPNode):
    """
    Cloud Scheduler — managed cron job.

    Connect to CloudRunNode    → HTTP POST trigger.
    Connect to CloudRunJobNode → Cloud Run Jobs API trigger.
    Connect to PubsubTopicNode → Pub/Sub publish trigger.
    """

    params_schema: ClassVar = [
        {
            "key": "name", "label": "Job Name",
            "type": "text", "default": "", "placeholder": "my-cron-job",
        },
        {
            "key": "schedule", "label": "Cron Schedule",
            "type": "text", "default": "0 * * * *", "placeholder": "0 * * * *",
        },
        {
            "key": "timezone", "label": "Timezone",
            "type": "text", "default": "UTC", "placeholder": "UTC",
        },
        {
            "key": "http_method", "label": "HTTP Method (Service targets)",
            "type": "select", "options": ["POST", "GET", "PUT", "PATCH"],
            "default": "POST",
        },
        {
            "key": "http_path", "label": "HTTP Path (Service targets)",
            "type": "text", "default": "/", "placeholder": "/tasks/run",
        },
        {
            "key": "http_body", "label": "HTTP Body (JSON)",
            "type": "text", "default": "{}", "placeholder": '{"key": "value"}',
        },
        {
            "key": "pubsub_message", "label": "Pub/Sub Message Body",
            "type": "text", "default": "{}", "placeholder": '{"key": "value"}',
        },
        {
            "key": "retry_count", "label": "Retry Count",
            "type": "number", "default": 3,
        },
    ]

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("triggers",     PortType.HTTP_TARGET, multi=True),  # → CloudRunNode
        Port("triggers_job", PortType.RUN_JOB,     multi=True),  # → CloudRunJobNode
        Port("publishes_to", PortType.TOPIC,        multi=True),  # → PubsubTopicNode
    ]

    node_color:  ClassVar = "#0ea5e9"
    icon:        ClassVar = "cloudScheduler"
    category:    ClassVar = "Orchestration"
    description: ClassVar = "Managed cron job service"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id != self.node_id:
            return False
        if tgt_type == "CloudRunNode":
            ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
            return True
        if tgt_type == "CloudRunJobNode":
            ctx[self.node_id].setdefault("target_job_ids", []).append(tgt_id)
            return True
        if tgt_type == "PubsubTopicNode":
            ctx[self.node_id].setdefault("target_topic_ids", []).append(tgt_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps  = list(ctx.get("target_run_ids",   []))
        deps += list(ctx.get("target_job_ids",   []))
        deps += list(ctx.get("target_topic_ids", []))
        sa_id = ctx.get("service_account_id")
        if sa_id:
            deps.append(sa_id)
        return deps

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "")

        target_run_ids   = ctx.get("target_run_ids",   [])
        target_job_ids   = ctx.get("target_job_ids",   [])
        target_topic_ids = ctx.get("target_topic_ids", [])

        def program() -> None:
            job_name  = props.get("name") or _resource_name(node_dict)
            schedule  = props.get("schedule",    "0 * * * *")
            timezone  = props.get("timezone",    "UTC")
            method    = props.get("http_method", "POST")
            path      = props.get("http_path",   "/")
            body      = props.get("http_body",   "{}")
            retry     = int(props.get("retry_count", 3))

            retry_cfg = gcp.cloudscheduler.JobRetryConfigArgs(retry_count=retry)

            # ── 1. HTTP target — Cloud Run Services ───────────────────────────
            for idx, run_id in enumerate(target_run_ids):
                run_outputs = deployed_outputs.get(run_id, {})
                service_url = run_outputs.get("uri", run_outputs.get("url", ""))
                if not service_url:
                    logger.warning("CloudSchedulerNode: no URL for CloudRunNode %s", run_id)
                    continue

                target_url = service_url.rstrip("/") + path
                oidc = None
                if sa_email:
                    oidc = gcp.cloudscheduler.JobHttpTargetOidcTokenArgs(
                        service_account_email=sa_email,
                        audience=service_url,
                    )

                suffix = f"-svc{idx}" if len(target_run_ids) > 1 else ""
                gcp.cloudscheduler.Job(
                    f"{self.node_id}-http{idx}",
                    name=f"{job_name}{suffix}",
                    schedule=schedule,
                    time_zone=timezone,
                    region=region,
                    project=project,
                    retry_config=retry_cfg,
                    http_target=gcp.cloudscheduler.JobHttpTargetArgs(
                        http_method=method,
                        uri=target_url,
                        body=body.encode() if body else None,
                        headers={"Content-Type": "application/json"},
                        oidc_token=oidc,
                    ),
                )
                pulumi.export(f"svc_job_name_{idx}", f"{job_name}{suffix}")
                pulumi.export(f"svc_target_url_{idx}", target_url)

            # ── 2. Cloud Run Job trigger ───────────────────────────────────────
            # Cloud Scheduler triggers a Cloud Run Job via an HTTP POST to the
            # Jobs run endpoint:
            #   POST https://{region}-run.googleapis.com/apis/run.googleapis.com/v1/
            #        namespaces/{project}/jobs/{job_name}:run
            # Auth: OIDC token with the Jobs Runner role on the SA.
            for idx, crun_job_id in enumerate(target_job_ids):
                job_outputs  = deployed_outputs.get(crun_job_id, {})
                crun_job_name = job_outputs.get("job_name", "")
                if not crun_job_name:
                    logger.warning(
                        "CloudSchedulerNode: no job_name for CloudRunJobNode %s", crun_job_id
                    )
                    continue

                # Cloud Run Jobs execution API endpoint
                run_job_url = (
                    f"https://{region}-run.googleapis.com"
                    f"/apis/run.googleapis.com/v1"
                    f"/namespaces/{project}/jobs/{crun_job_name}:run"
                )

                oidc = None
                if sa_email:
                    oidc = gcp.cloudscheduler.JobHttpTargetOidcTokenArgs(
                        service_account_email=sa_email,
                        audience=f"https://{region}-run.googleapis.com/",
                    )

                suffix = f"-job{idx}" if len(target_job_ids) > 1 else "-job"
                gcp.cloudscheduler.Job(
                    f"{self.node_id}-runjob{idx}",
                    name=f"{job_name}{suffix}",
                    schedule=schedule,
                    time_zone=timezone,
                    region=region,
                    project=project,
                    retry_config=retry_cfg,
                    http_target=gcp.cloudscheduler.JobHttpTargetArgs(
                        http_method="POST",
                        uri=run_job_url,
                        body=b"{}",
                        headers={"Content-Type": "application/json"},
                        oidc_token=oidc,
                    ),
                )
                pulumi.export(f"run_job_scheduler_{idx}", f"{job_name}{suffix}")
                pulumi.export(f"run_job_target_{idx}", crun_job_name)

            # ── 3. Pub/Sub target ─────────────────────────────────────────────
            pubsub_message = props.get("pubsub_message", "{}")
            for idx, topic_id in enumerate(target_topic_ids):
                topic_name = deployed_outputs.get(topic_id, {}).get("name", "")
                if not topic_name:
                    logger.warning("CloudSchedulerNode: no name for topic %s", topic_id)
                    continue

                topic_path = f"projects/{project}/topics/{topic_name}"
                suffix     = f"-pub{idx}" if len(target_topic_ids) > 1 else "-pub"

                gcp.cloudscheduler.Job(
                    f"{self.node_id}-pub{idx}",
                    name=f"{job_name}{suffix}",
                    schedule=schedule,
                    time_zone=timezone,
                    region=region,
                    project=project,
                    retry_config=retry_cfg,
                    pubsub_target=gcp.cloudscheduler.JobPubsubTargetArgs(
                        topic_name=topic_path,
                        data=pubsub_message.encode() if pubsub_message else None,
                    ),
                )
                pulumi.export(f"pubsub_job_name_{idx}", f"{job_name}{suffix}")

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return LogSource(
            filter=(
                f'resource.type="cloud_scheduler_job"'
                f' AND resource.labels.location="{region}"'
            ),
            project=project,
        )