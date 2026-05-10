"""
nodes/pubsub.py — Pub/Sub resource nodes (fully self-describing).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_label
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

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
        {"key": "use_topic_schema", "label": "Use Topic Schema",                     "type": "checkbox", "default": True},
        {"key": "write_metadata",   "label": "Write Metadata",                       "type": "checkbox", "default": False},
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