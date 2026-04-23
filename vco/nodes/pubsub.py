"""
nodes/pubsub.py — Pub/Sub resource nodes (fully self-describing).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_label
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


# ── PubSub Topic ──────────────────────────────────────────────────────────────

@dataclass
class PubsubTopicNode(GCPNode):
    # name:                 str = ""
    # test_message:         str = ""    
    message_retention_duration: str = "604800s"
    kms_key_name:               str = ""

    params_schema: ClassVar = [
        {"key": "name",                 "label": "Topic Name",         "type": "text", "default": "", "placeholder": "your-topic-name"},
        {"key": "message_retention_duration", "label": "Retention Duration", "type": "text", "default": "604800s"},
        {"key": "kms_key_name",               "label": "KMS Key Name",       "type": "text", "default": ""},
    ]   
    inputs:  ClassVar = [Port("publishers",    PortType.TOPIC,        multi_in=True)]
    outputs: ClassVar = [Port("subscriptions", PortType.SUBSCRIPTION, multi=True)]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Pub/Sub Topic — the core messaging hub"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if tgt_id == self.node_id and tgt_type == "PubsubTopicNode":
            ctx[self.node_id].setdefault("publisher_ids", []).append(src_id)
            return True
        if src_id == self.node_id and src_type == "PubsubTopicNode":
            ctx[tgt_id]["topic_id"] = self.node_id
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        def program() -> None:
            name = props.get("topic_name") or _resource_name(node_dict)
            t = gcp.pubsub.Topic(
                self.node_id,
                name=name,
                message_retention_duration=props.get("message_retention_duration", "604800s"),
                project=project,
            )
            pulumi.export("name", t.name)
            pulumi.export("id",   t.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        # Topics have no interesting URL to show, just expose the name
        return {"topic_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="pubsub_topic"'
                f' AND resource.labels.topic_id="{name}"'
            ),
            project=project,
        )


# ── PubSub Pull Subscription ──────────────────────────────────────────────────

@dataclass
class PubsubPullSubscriptionNode(GCPNode):
    ack_deadline_seconds:         int  = 20
    filter:                       str  = ""
    enable_message_ordering:      bool = False
    enable_exactly_once_delivery: bool = False
    service_account:              str  = ""
    dead_letter_topic:            str  = ""

    params_schema: ClassVar = [
        {"key": "ack_deadline_seconds",        "label": "Ack Deadline (s)",      "type": "number",  "default": 20},
        {"key": "filter",                       "label": "Filter Expression",     "type": "text",    "default": ""},
        {"key": "enable_message_ordering",      "label": "Message Ordering",      "type": "boolean", "default": False},
        {"key": "enable_exactly_once_delivery", "label": "Exactly Once Delivery", "type": "boolean", "default": False},
        {"key": "service_account",              "label": "Service Account Email", "type": "text",    "default": ""},
        {"key": "dead_letter_topic",            "label": "Dead Letter Topic",     "type": "text",    "default": ""},
    ]
    inputs:  ClassVar = [Port("topic_link", PortType.SUBSCRIPTION, required=True)]
    outputs: ClassVar = [Port("messages",   PortType.MESSAGE,       multi=True)]
    node_color:  ClassVar = "#ec485b"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Standard Pull Subscription"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and src_type == "PubsubPullSubscriptionNode":
            ctx[self.node_id].setdefault("consumer_ids", []).append(tgt_id)
            ctx[tgt_id].setdefault("receives_from_subs", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return [ctx["topic_id"]] if ctx.get("topic_id") else []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict  = ctx.get("node", {})
        props      = node_dict.get("props", {})
        topic_name = deployed_outputs.get(ctx.get("topic_id", ""), {}).get("name", "")

        if not topic_name:
            logger.warning("PubsubPullSubscriptionNode %s: topic not deployed — skipping", self.node_id)
            return None

        def program() -> None:
            sub = gcp.pubsub.Subscription(
                self.node_id,
                name=_resource_name(node_dict),
                topic=topic_name,
                ack_deadline_seconds=props.get("ack_deadline_seconds", 20),
                project=project,
            )
            pulumi.export("name", sub.name)
            pulumi.export("id",   sub.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"subscription_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="pubsub_subscription"'
                f' AND resource.labels.subscription_id="{name}"'
            ),
            project=project,
        )


# ── PubSub Push Subscription ──────────────────────────────────────────────────

@dataclass
class PubsubPushSubscriptionNode(GCPNode):
    push_endpoint:              str = ""
    ack_deadline_seconds:       int = 20
    oidc_service_account_email: str = ""
    audience:                   str = ""
    expiration_policy:          str = "1209600s"
    filter:                     str = ""

    params_schema: ClassVar = [
        {"key": "push_endpoint",              "label": "Push Endpoint URL",    "type": "text",   "default": "", "placeholder": "https://..."},
        {"key": "ack_deadline_seconds",        "label": "Ack Deadline (s)",     "type": "number", "default": 20},
        {"key": "oidc_service_account_email",  "label": "OIDC Service Account", "type": "text",   "default": ""},
        {"key": "audience",                    "label": "Audience",             "type": "text",   "default": ""},
        {"key": "filter",                      "label": "Filter",               "type": "text",   "default": ""},
    ]
    inputs:  ClassVar = [Port("topic_link", PortType.SUBSCRIPTION, required=True)]
    outputs: ClassVar = [Port("messages",   PortType.MESSAGE,       multi=True)]
    node_color:  ClassVar = "#ef4444"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Push Subscription to Webhook/Service"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and src_type == "PubsubPushSubscriptionNode":
            ctx[self.node_id].setdefault("push_target_ids", []).append(tgt_id)
            ctx[tgt_id].setdefault("receives_from_subs", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = []
        if ctx.get("topic_id"):
            deps.append(ctx["topic_id"])
        deps.extend(ctx.get("push_target_ids", []))
        return deps

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict  = ctx.get("node", {})
        props      = node_dict.get("props", {})
        topic_name = deployed_outputs.get(ctx.get("topic_id", ""), {}).get("name", "")

        if not topic_name:
            logger.warning("PubsubPushSubscriptionNode %s: topic not deployed — skipping", self.node_id)
            return None

        push_target_ids = ctx.get("push_target_ids", [])
        push_endpoint   = (
            deployed_outputs[push_target_ids[0]].get("uri", "")
            if push_target_ids and push_target_ids[0] in deployed_outputs
            else props.get("push_endpoint", "")
        )
        oidc_sa = props.get("oidc_service_account_email", "")

        def program() -> None:
            sub = gcp.pubsub.Subscription(
                self.node_id,
                name=_resource_name(node_dict),
                topic=topic_name,
                ack_deadline_seconds=props.get("ack_deadline_seconds", 20),
                project=project,
                push_config=gcp.pubsub.SubscriptionPushConfigArgs(
                    push_endpoint=push_endpoint,
                    oidc_token=(
                        gcp.pubsub.SubscriptionPushConfigOidcTokenArgs(
                            service_account_email=oidc_sa,
                        ) if oidc_sa else None
                    ),
                ),
            )
            pulumi.export("name", sub.name)
            pulumi.export("id",   sub.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"subscription_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="pubsub_subscription"'
                f' AND resource.labels.subscription_id="{name}"'
            ),
            project=project,
        )


# ── BigQuery Subscription ─────────────────────────────────────────────────────

@dataclass
class PubsubBigQuerySubscriptionNode(GCPNode):
    table:               str  = ""
    use_topic_schema:    bool = True
    use_table_schema:    bool = False
    write_metadata:      bool = False
    drop_unknown_fields: bool = False

    params_schema: ClassVar = [
        {"key": "table",            "label": "Target Table (project.dataset.table)", "type": "text",    "default": ""},
        {"key": "use_topic_schema", "label": "Use Topic Schema",                     "type": "boolean", "default": True},
        {"key": "write_metadata",   "label": "Write Metadata",                       "type": "boolean", "default": False},
    ]
    inputs:  ClassVar = [Port("topic_link", PortType.SUBSCRIPTION, required=True)]
    outputs: ClassVar = [Port("bq_table",   PortType.DATABASE)]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "BigQuery Push Subscription"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        return False  # topic_id set by PubsubTopicNode

    def dag_deps(self, ctx) -> list[str]:
        return [ctx["topic_id"]] if ctx.get("topic_id") else []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict  = ctx.get("node", {})
        props      = node_dict.get("props", {})
        topic_name = deployed_outputs.get(ctx.get("topic_id", ""), {}).get("name", "")

        if not topic_name:
            logger.warning("PubsubBigQuerySubscriptionNode %s: topic not deployed — skipping", self.node_id)
            return None

        def program() -> None:
            sub = gcp.pubsub.Subscription(
                self.node_id,
                name=_resource_name(node_dict),
                topic=topic_name,
                project=project,
                bigquery_config=gcp.pubsub.SubscriptionBigqueryConfigArgs(
                    table=props.get("table", ""),
                    use_topic_schema=props.get("use_topic_schema", True),
                    write_metadata=props.get("write_metadata", False),
                    drop_unknown_fields=props.get("drop_unknown_fields", False),
                ),
            )
            pulumi.export("name", sub.name)
            pulumi.export("id",   sub.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"subscription_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="pubsub_subscription"'
                f' AND resource.labels.subscription_id="{name}"'
            ),
            project=project,
        )


# ── Cloud Storage Subscription ────────────────────────────────────────────────

@dataclass
class PubsubCloudStorageSubscriptionNode(GCPNode):
    bucket:                   str = ""
    filename_prefix:          str = "log_events_"
    filename_suffix:          str = ".avro"
    filename_datetime_format: str = "YYYY-MM-DD/hh_mm_ssZ"
    max_duration:             str = "60s"
    max_bytes:                str = "10000000"
    output_format:            str = "avro"

    params_schema: ClassVar = [
        {"key": "bucket",          "label": "GCS Bucket Name", "type": "text",   "default": ""},
        {"key": "filename_prefix", "label": "Prefix",          "type": "text",   "default": "log_events_"},
        {"key": "output_format",   "label": "Format",          "type": "select", "options": ["avro", "text"], "default": "avro"},
        {"key": "max_duration",    "label": "Max Duration",    "type": "text",   "default": "60s"},
    ]
    inputs:  ClassVar = [Port("topic_link", PortType.SUBSCRIPTION, required=True)]
    outputs: ClassVar = [Port("gcs_bucket", PortType.STORAGE)]
    node_color:  ClassVar = "#eab308"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Cloud Storage Push Subscription"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        return False

    def dag_deps(self, ctx) -> list[str]:
        return [ctx["topic_id"]] if ctx.get("topic_id") else []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict  = ctx.get("node", {})
        props      = node_dict.get("props", {})
        topic_name = deployed_outputs.get(ctx.get("topic_id", ""), {}).get("name", "")

        if not topic_name:
            logger.warning("PubsubCloudStorageSubscriptionNode %s: topic not deployed — skipping", self.node_id)
            return None

        fmt = props.get("output_format", "avro")

        def program() -> None:
            sub = gcp.pubsub.Subscription(
                self.node_id,
                name=_resource_name(node_dict),
                topic=topic_name,
                project=project,
                cloud_storage_config=gcp.pubsub.SubscriptionCloudStorageConfigArgs(
                    bucket=props.get("bucket", ""),
                    filename_prefix=props.get("filename_prefix", "log_events_"),
                    filename_suffix=props.get("filename_suffix", ".avro"),
                    filename_datetime_format=props.get("filename_datetime_format", "YYYY-MM-DD/hh_mm_ssZ"),
                    max_duration=props.get("max_duration", "60s"),
                    max_bytes=int(props.get("max_bytes", 10_000_000)),
                    avro_config=(
                        gcp.pubsub.SubscriptionCloudStorageConfigAvroConfigArgs(
                            write_metadata=props.get("write_metadata", False),
                        ) if fmt == "avro" else None
                    ),
                ),
            )
            pulumi.export("name", sub.name)
            pulumi.export("id",   sub.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"subscription_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return None  # GCS subscription writes files, not log entries