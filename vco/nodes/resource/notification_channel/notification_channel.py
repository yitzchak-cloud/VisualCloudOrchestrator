"""
nodes/resource/notification_channel/notification_channel.py
============================================================
NotificationChannelNode — Generic GCP notification channel.

Topology
--------
  GcsBucketNode        ──(NOTIFICATION)──► NotificationChannelNode
  PubsubTopicNode      ──(NOTIFICATION)──► NotificationChannelNode
  CloudRunNode         ──(NOTIFICATION)──► NotificationChannelNode
  CloudFunctionsNode   ──(NOTIFICATION)──► NotificationChannelNode
  CloudSchedulerNode   ──(NOTIFICATION)──► NotificationChannelNode
  BigQueryNode         ──(NOTIFICATION)──► NotificationChannelNode
  CloudSqlNode         ──(NOTIFICATION)──► NotificationChannelNode
  WorkflowNode         ──(NOTIFICATION)──► NotificationChannelNode

  NotificationChannelNode ──(SERVICE_ACCOUNT)──► ServiceAccountNode (optional)

The notification TYPE is determined at deployment time by inspecting which
source node is wired in — no manual selection needed.

Supported source → GCP notification type mapping:
  GcsBucketNode      → google.storage.object.finalize / delete / archive / metadataUpdate
  PubsubTopicNode    → Pub/Sub push subscription to the channel
  CloudRunNode       → Cloud Monitoring Alerting (uptime / error rate)
  CloudFunctionsNode → Cloud Monitoring Alerting (error rate / execution count)
  BigQueryNode       → Cloud Monitoring Alerting (slot usage / bytes processed)
  CloudSqlNode       → Cloud Monitoring Alerting (disk / memory / connections)
  CloudSchedulerNode → Monitoring Alerting (job failure)
  WorkflowNode       → Monitoring Alerting (execution failure)

Exports (Pulumi outputs)
------------------------
  name          — notification channel display name
  channel_type  — email | slack | pagerduty | webhook | pubsub
  channel_name  — GCP channel resource name (for linking to alert policies)
  source_type   — class name of the wired source node
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

from nodes.resource.notification_channel._pulumi import make_pulumi_program
from nodes.resource.notification_channel._terraform import (
    make_terraform_call_vars,
    terraform_instance_prefix as _tf_prefix,
)

logger = logging.getLogger(__name__)


# ── Context keys ──────────────────────────────────────────────────────────────
class K:
    SOURCE_ID        = "source_id"
    SOURCE_TYPE      = "source_type"          # e.g. "GcsBucketNode"
    SERVICE_ACCOUNT  = "service_account_id"


# ── Source node → notification intent mapping ─────────────────────────────────
# Used by the Pulumi program to decide what alert policy / binding to create.
SOURCE_INTENT: dict[str, str] = {
    "GcsBucketNode":        "gcs_object_change",
    "PubsubTopicNode":      "pubsub_message",
    "CloudRunNode":         "cloud_run_error",
    "CloudFunctionsNode":   "cloud_functions_error",
    "BigQueryNode":         "bigquery_slot_usage",
    "CloudSqlNode":         "cloudsql_resource",
    "CloudSchedulerNode":   "scheduler_job_failure",
    "WorkflowNode":         "workflow_execution_failure",
}


@dataclass
class NotificationChannelNode(GCPNode):
    """
    Generic GCP notification channel.

    Wire any resource → this node to create a monitoring notification channel
    for that resource.  The channel type (email, Slack, PagerDuty, webhook,
    or Pub/Sub) is chosen via the params panel — it is independent of which
    resource is wired in.

    The wired source node determines *what* is monitored (the alert policy
    or GCS notification binding that is created alongside the channel).
    """

    inputs: ClassVar = [
        Port("source",          PortType.NOTIFICATION,   required=True),
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = []   # terminal node — no outputs

    node_color:  ClassVar = "#6366f1"        # indigo
    icon:        ClassVar = "notifications"  # Material icon fallback
    category:    ClassVar = "Operations"
    description: ClassVar = (
        "GCP Monitoring notification channel. "
        "Wire a resource to this node to receive alerts for that resource."
    )

    # ── Edge wiring ───────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # We are the TARGET — accept any source that has a NOTIFICATION port
        if tgt_id == self.node_id:
            if src_type in SOURCE_INTENT:
                ctx[self.node_id][K.SOURCE_ID]   = src_id
                ctx[self.node_id][K.SOURCE_TYPE]  = src_type
                return True
            if src_type == "ServiceAccountNode":
                ctx[self.node_id][K.SERVICE_ACCOUNT] = src_id
                return True
        return False

    # ── DAG deps ──────────────────────────────────────────────────────────────

    def dag_deps(self, ctx) -> list[str]:
        deps = []
        if ctx.get(K.SOURCE_ID):
            deps.append(ctx[K.SOURCE_ID])
        if ctx.get(K.SERVICE_ACCOUNT):
            deps.append(ctx[K.SERVICE_ACCOUNT])
        return deps

    # ── Pulumi ────────────────────────────────────────────────────────────────

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        self._props = ctx.get("node", {}).get("props", {})
        return make_pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs)

    # ── Terraform ─────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return _tf_prefix()

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        self._props = ctx.get("node", {}).get("props", {})
        return make_terraform_call_vars(self, ctx, project, region, all_nodes)

    # ── Live outputs ──────────────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "name":         pulumi_outputs.get("name", ""),
            "channel_type": pulumi_outputs.get("channel_type", ""),
            "channel_name": pulumi_outputs.get("channel_name", ""),
            "source_type":  pulumi_outputs.get("source_type", ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return None   # Monitoring channels don't emit structured logs
