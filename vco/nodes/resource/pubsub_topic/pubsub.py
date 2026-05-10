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


    @property
    def terraform_instance_prefix(self): return "topic"

    def terraform_call_vars(self, ctx, project, region, all_nodes):
        from nodes.base_node import _resource_name, _tf_name
        props = ctx.get("node", {}).get("props", {})
        return {
            "name":      f'"{props.get("name") or _resource_name(ctx.get("node",{}))}"  ',
            "retention": f'"{props.get("message_retention_duration", "604800s")}"',
        }

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

