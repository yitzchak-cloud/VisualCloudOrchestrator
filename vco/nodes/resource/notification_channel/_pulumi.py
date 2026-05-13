"""
nodes/resource/notification_channel/_pulumi.py
===============================================
Pulumi program factory for NotificationChannelNode.

Strategy
--------
1. Always create a google_monitoring_notification_channel (type driven by props).
2. Then, based on which source node is wired (ctx[K.SOURCE_TYPE]), create the
   appropriate binding:

   GcsBucketNode      → gcp.storage.Notification  (GCS native notification)
   PubsubTopicNode    → gcp.monitoring.AlertPolicy (pubsub message count alert)
   CloudRunNode       → gcp.monitoring.AlertPolicy (request error rate alert)
   CloudFunctionsNode → gcp.monitoring.AlertPolicy (function error count alert)
   BigQueryNode       → gcp.monitoring.AlertPolicy (slot utilisation alert)
   CloudSqlNode       → gcp.monitoring.AlertPolicy (disk usage alert)
   CloudSchedulerNode → gcp.monitoring.AlertPolicy (job failure alert)
   WorkflowNode       → gcp.monitoring.AlertPolicy (execution failure alert)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import _resource_name

if TYPE_CHECKING:
    from nodes.resource.notification_channel.notification_channel import NotificationChannelNode

logger = logging.getLogger(__name__)

# ── channel_type → GCP type string ───────────────────────────────────────────
_GCP_CHANNEL_TYPE: dict[str, str] = {
    "email":      "email",
    "slack":      "slack",
    "pagerduty":  "pagerduty",
    "webhook":    "webhook_tokenauth",
    "pubsub":     "pubsub",
}


def make_pulumi_program(
    node:             "NotificationChannelNode",
    ctx:              dict[str, Any],
    project:          str,
    region:           str,
    all_nodes:        list[dict],
    deployed_outputs: dict[str, dict],
) -> Callable[[], None]:
    node_dict   = ctx.get("node", {})
    props       = node_dict.get("props", {})
    source_id   = ctx.get("source_id", "")
    source_type = ctx.get("source_type", "")
    sa_id       = ctx.get("service_account_id", "")
    sa_email    = deployed_outputs.get(sa_id, {}).get("email", "")

    # Outputs from the source node
    source_outputs = deployed_outputs.get(source_id, {})
    source_name    = source_outputs.get("name", "")

    channel_type = props.get("channel_type", "email")
    display_name = props.get("name") or _resource_name(node_dict) or "notification-channel"
    alert_name   = props.get("alert_display_name") or f"{source_name}-alert"
    duration_sec = int(props.get("alert_duration_seconds", 60))
    auto_close   = int(props.get("auto_close_seconds", 86400))

    def program() -> None:
        # ── 1. Build channel labels dict based on type ────────────────────────
        labels = _build_channel_labels(channel_type, props)

        gcp_type = _GCP_CHANNEL_TYPE.get(channel_type, "email")

        channel = gcp.monitoring.NotificationChannel(
            f"nc-{node.node_id}",
            display_name=display_name,
            type=gcp_type,
            labels=labels,
            project=project,
        )

        pulumi.export("name",         display_name)
        pulumi.export("channel_type", channel_type)
        pulumi.export("channel_name", channel.name)
        pulumi.export("source_type",  source_type)

        if not source_type or not source_name:
            logger.warning(
                "NotificationChannelNode %s: no source wired — skipping alert policy / binding",
                node.node_id,
            )
            return

        # ── 2. Create the binding / alert policy based on source type ─────────
        if source_type == "GcsBucketNode":
            _create_gcs_notification(node, props, project, source_name, channel)
        else:
            _create_alert_policy(
                node, source_type, project, source_name,
                alert_name, duration_sec, auto_close, channel,
            )

    return program


# ── Channel label helpers ─────────────────────────────────────────────────────

def _build_channel_labels(channel_type: str, props: dict) -> dict:
    if channel_type == "email":
        return {"email_address": props.get("email_address", "")}
    if channel_type == "slack":
        return {
            "channel_name": props.get("slack_channel_name", ""),
            "auth_token":   props.get("slack_auth_token", ""),
        }
    if channel_type == "pagerduty":
        return {"service_key": props.get("pagerduty_service_key", "")}
    if channel_type == "webhook":
        labels = {"url": props.get("webhook_url", "")}
        if props.get("webhook_username"):
            labels["username"] = props["webhook_username"]
        if props.get("webhook_password"):
            labels["password"] = props["webhook_password"]
        return labels
    if channel_type == "pubsub":
        return {"topic": props.get("pubsub_topic", "")}
    return {}


# ── GCS native notification ───────────────────────────────────────────────────

def _create_gcs_notification(node, props, project, bucket_name, channel):
    """
    Use the GCS Notifications API to send storage events directly.
    The 'channel' here is a Pub/Sub topic in GCS's model, so we create
    a monitoring alert policy for non-Pub/Sub channels and a native
    gcp.storage.Notification for Pub/Sub channels.
    """
    event_type = props.get("gcs_event_types", "OBJECT_FINALIZE")

    channel_type = props.get("channel_type", "email")

    if channel_type == "pubsub":
        # GCS can push directly to Pub/Sub
        pubsub_topic = props.get("pubsub_topic", "")
        if pubsub_topic:
            gcp.storage.Notification(
                f"gcs-notif-{node.node_id}",
                bucket=bucket_name,
                payload_format="JSON_API_V1",
                topic=pubsub_topic,
                event_types=[event_type],
            )
    else:
        # For email/slack/pagerduty/webhook — create a Monitoring alert policy
        # that watches GCS object count changes as a proxy event
        _create_alert_policy(
            node, "GcsBucketNode", project, bucket_name,
            f"{bucket_name}-gcs-alert", 0, 86400, channel,
            extra_filter=f'resource.labels.bucket_name="{bucket_name}"',
            metric="storage.googleapis.com/storage/object_count",
            comparison="COMPARISON_GT",
            threshold=0,
        )


# ── Monitoring alert policy ───────────────────────────────────────────────────

# Metric configs per source node type
_METRIC_CONFIG: dict[str, dict] = {
    "CloudRunNode": {
        "metric":      "run.googleapis.com/request_count",
        "filter_key":  "resource.labels.service_name",
        "comparison":  "COMPARISON_GT",
        "threshold":   0,
        "extra_filter": 'metric.labels.response_code_class="5xx"',
    },
    "CloudFunctionsNode": {
        "metric":      "cloudfunctions.googleapis.com/function/execution_count",
        "filter_key":  "resource.labels.function_name",
        "comparison":  "COMPARISON_GT",
        "threshold":   0,
        "extra_filter": 'metric.labels.status!="ok"',
    },
    "PubsubTopicNode": {
        "metric":      "pubsub.googleapis.com/topic/message_count",
        "filter_key":  "resource.labels.topic_id",
        "comparison":  "COMPARISON_GT",
        "threshold":   1000,
        "extra_filter": "",
    },
    "BigQueryNode": {
        "metric":      "bigquery.googleapis.com/slot_utilization",
        "filter_key":  "resource.labels.project_id",
        "comparison":  "COMPARISON_GT",
        "threshold":   0.9,
        "extra_filter": "",
    },
    "CloudSqlNode": {
        "metric":      "cloudsql.googleapis.com/database/disk/utilization",
        "filter_key":  "resource.labels.database_id",
        "comparison":  "COMPARISON_GT",
        "threshold":   0.85,
        "extra_filter": "",
    },
    "CloudSchedulerNode": {
        "metric":      "cloudscheduler.googleapis.com/job/attempt_count",
        "filter_key":  "resource.labels.job_id",
        "comparison":  "COMPARISON_GT",
        "threshold":   0,
        "extra_filter": 'metric.labels.status="FAILED"',
    },
    "WorkflowNode": {
        "metric":      "workflows.googleapis.com/finished_execution_count",
        "filter_key":  "resource.labels.workflow_id",
        "comparison":  "COMPARISON_GT",
        "threshold":   0,
        "extra_filter": 'metric.labels.status="FAILED"',
    },
    "GcsBucketNode": {
        "metric":      "storage.googleapis.com/storage/object_count",
        "filter_key":  "resource.labels.bucket_name",
        "comparison":  "COMPARISON_GT",
        "threshold":   0,
        "extra_filter": "",
    },
}


def _create_alert_policy(
    node,
    source_type:   str,
    project:       str,
    source_name:   str,
    alert_name:    str,
    duration_sec:  int,
    auto_close:    int,
    channel,
    extra_filter:  str = "",
    metric:        str = "",
    comparison:    str = "",
    threshold:     float = 0,
):
    cfg = _METRIC_CONFIG.get(source_type, {})
    metric      = metric      or cfg.get("metric", "")
    comparison  = comparison  or cfg.get("comparison", "COMPARISON_GT")
    threshold   = threshold   if threshold else cfg.get("threshold", 0)
    filter_key  = cfg.get("filter_key", "")
    extra       = extra_filter or cfg.get("extra_filter", "")

    if not metric:
        logger.warning(
            "NotificationChannelNode: no metric config for source type '%s' — skipping alert",
            source_type,
        )
        return

    mql_filter = f'metric.type="{metric}"'
    if filter_key and source_name:
        mql_filter += f' AND {filter_key}="{source_name}"'
    if extra:
        mql_filter += f" AND {extra}"

    gcp.monitoring.AlertPolicy(
        f"alert-{node.node_id}",
        display_name=alert_name,
        project=project,
        combiner="OR",
        conditions=[
            gcp.monitoring.AlertPolicyConditionArgs(
                display_name=f"{source_type} condition",
                condition_threshold=gcp.monitoring.AlertPolicyConditionConditionThresholdArgs(
                    filter=mql_filter,
                    comparison=comparison,
                    threshold_value=threshold,
                    duration=f"{duration_sec}s",
                    aggregations=[
                        gcp.monitoring.AlertPolicyConditionConditionThresholdAggregationArgs(
                            alignment_period="60s",
                            per_series_aligner="ALIGN_RATE",
                        )
                    ],
                ),
            )
        ],
        notification_channels=[channel.name],
        alert_strategy=gcp.monitoring.AlertPolicyAlertStrategyArgs(
            auto_close=f"{auto_close}s",
        ),
    )
