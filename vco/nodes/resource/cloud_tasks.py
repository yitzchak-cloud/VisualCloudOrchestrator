"""
nodes/cloud_tasks.py — Cloud Tasks Queue resource node (fully self-describing).

Changes from previous version
------------------------------
  • Added iam_binding input port (so IamBindingNode can target this queue).

Topology
--------
  CloudTasksQueueNode ──(TASK_QUEUE)──► CloudRunNode

  IamBindingNode ──(IAM_BINDING)──► CloudTasksQueueNode  ← NEW
    e.g. grant roles/cloudtasks.enqueuer to a SA

Creates a Cloud Tasks queue. The wired CloudRunNode URL is stored as the
queue's default HTTP target so that the application only needs to know the
queue name — not the destination URL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class CloudTasksQueueNode(GCPNode):
    """
    Cloud Tasks Queue — asynchronous task execution.

    Connect to CloudRunNode → tasks are dispatched via HTTPS POST to that service.
    Connect IamBindingNode → this queue to grant roles (e.g. cloudtasks.enqueuer).
    """

    params_schema: ClassVar = [
        {
            "key": "name", "label": "Queue Name",
            "type": "text", "default": "", "placeholder": "my-task-queue",
        },
        {
            "key": "http_path", "label": "Handler Path",
            "type": "text", "default": "/tasks/handle", "placeholder": "/tasks/handle",
        },
        {
            "key": "max_concurrent", "label": "Max Concurrent Dispatches",
            "type": "number", "default": 100,
        },
        {
            "key": "max_attempts", "label": "Max Attempts",
            "type": "number", "default": 5,
        },
        {
            "key": "min_backoff", "label": "Min Backoff (seconds)",
            "type": "number", "default": 10,
        },
        {
            "key": "max_backoff", "label": "Max Backoff (seconds)",
            "type": "number", "default": 300,
        },
        {
            "key": "max_dispatches_per_second", "label": "Max Dispatches / second",
            "type": "number", "default": 500,
        },
    ]

    inputs: ClassVar = [
        Port("none",            PortType.TASK_QUEUE,       multi=True),
        Port("service_account", PortType.SERVICE_ACCOUNT,  required=False),
        Port("iam_binding",     PortType.IAM_BINDING,      required=False, multi=True, multi_in=True),  # NEW
    ]
    outputs: ClassVar = [
        Port("dispatches_to", PortType.TASK_QUEUE, multi=True),
    ]

    node_color:  ClassVar = "#fb7185"
    icon:        ClassVar = "cloudTasks"
    category:    ClassVar = "Integration_Services"
    description: ClassVar = "Asynchronous task execution queue"

    # ------------------------------------------------------------------
    # Terraform static-module interface
    # ------------------------------------------------------------------

    @property
    def terraform_dir(self):
        from pathlib import Path
        return Path(__file__).parent / "terraform" / "cloud_tasks_queue"

    @property
    def terraform_instance_prefix(self): return "queue"

    def terraform_call_vars(self, ctx, project, region, all_nodes):
        from nodes.base_node import _resource_name, _tf_name, _node_by_id
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        cv = {
            "name":                      f'"{props.get("name") or _resource_name(node_dict)}"',
            "max_concurrent":            str(int(props.get("max_concurrent", 100))),
            "max_dispatches_per_second": str(int(props.get("max_dispatches_per_second", 500))),
            "max_attempts":              str(int(props.get("max_attempts", 5))),
            "min_backoff":               str(int(props.get("min_backoff", 10))),
            "max_backoff":               str(int(props.get("max_backoff", 300))),
            "handler_path":              f'"{props.get("http_path", "/tasks/handle")}"',
        }
        run_ids = ctx.get("target_run_ids", [])
        if run_ids:
            cv["handler_uri"] = f"module.cr_{_tf_name(_node_by_id(all_nodes, run_ids[0]))}.uri"
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            cv["sa_email"] = f"module.sa_{_tf_name(_node_by_id(all_nodes, sa_id))}.email"
        return cv

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id != self.node_id:
            return False
        if tgt_type == "CloudRunNode":
            ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
            # Also tell the CR about this queue so it gets env vars
            ctx[tgt_id].setdefault("task_queue_ids", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps  = list(ctx.get("target_run_ids", []))
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

        target_run_ids = ctx.get("target_run_ids", [])

        def program() -> None:
            queue_name           = props.get("name") or _resource_name(node_dict)
            http_path            = props.get("http_path", "/tasks/handle")
            max_concurrent       = int(props.get("max_concurrent", 100))
            max_attempts         = int(props.get("max_attempts", 5))
            min_backoff          = int(props.get("min_backoff", 10))
            max_backoff          = int(props.get("max_backoff", 300))
            max_dispatches_per_s = int(props.get("max_dispatches_per_second", 500))

            # Build the HTTP target URI from the first wired CR (most common case)
            http_target_uri: str | None = None
            for run_id in target_run_ids:
                uri = deployed_outputs.get(run_id, {}).get("uri", "")
                if uri:
                    http_target_uri = uri.rstrip("/") + http_path
                    break

            oidc_cfg = None
            if sa_email and http_target_uri:
                oidc_cfg = gcp.cloudtasks.QueueHttpTargetOidcTokenArgs(
                    service_account_email=sa_email,
                    audience=http_target_uri,
                )

            http_target_cfg = None
            if http_target_uri:
                http_target_cfg = gcp.cloudtasks.QueueHttpTargetArgs(
                    uri_override=gcp.cloudtasks.QueueHttpTargetUriOverrideArgs(
                        scheme="HTTPS",
                        host=http_target_uri.split("//")[-1].split("/")[0],
                        path_override=gcp.cloudtasks.QueueHttpTargetUriOverridePathOverrideArgs(
                            path=http_path,
                        ),
                    ),
                    http_method="POST",
                    oidc_token=oidc_cfg,
                )

            q = gcp.cloudtasks.Queue(
                self.node_id,
                name=queue_name,
                location=region,
                project=project,
                rate_limits=gcp.cloudtasks.QueueRateLimitsArgs(
                    max_concurrent_dispatches=max_concurrent,
                    max_dispatches_per_second=max_dispatches_per_s,
                ),
                retry_config=gcp.cloudtasks.QueueRetryConfigArgs(
                    max_attempts=max_attempts,
                    min_backoff=f"{min_backoff}s",
                    max_backoff=f"{max_backoff}s",
                ),
                http_target=http_target_cfg,
            )

            pulumi.export("queue_name",  q.name)
            pulumi.export("queue_id",    q.id)
            pulumi.export("handler_url", http_target_uri or "")

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"name": pulumi_outputs.get("queue_name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("queue_name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="cloudtasks.googleapis.com/Queue"'
                f' AND resource.labels.queue_id="{name}"'
            ),
            project=project,
        )