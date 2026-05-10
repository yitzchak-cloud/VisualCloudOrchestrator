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
        {"key": "enable_message_ordering",      "label": "Message Ordering",      "type": "checkbox", "default": False},
        {"key": "enable_exactly_once_delivery", "label": "Exactly Once Delivery", "type": "checkbox", "default": False},
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


    @property
    def terraform_dir(self):
        return Path(__file__).parent / "terraform" / "pubsub_pull_subscription"

    @property
    def terraform_instance_prefix(self): return "pull_sub"

    def terraform_call_vars(self, ctx, project, region, all_nodes):
        from nodes.base_node import _resource_name, _tf_name, _node_by_id
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        cv = {
            "name":                         f'"{_resource_name(node_dict)}"',
            "ack_deadline_seconds":         str(int(props.get("ack_deadline_seconds", 20))),
            "enable_message_ordering":      "true" if props.get("enable_message_ordering") else "false",
            "enable_exactly_once_delivery": "true" if props.get("enable_exactly_once_delivery") else "false",
        }
        topic_id = ctx.get("topic_id", "")
        cv["topic_name"] = f"module.topic_{_tf_name(_node_by_id(all_nodes, topic_id))}.name" if topic_id else '""'
        if props.get("filter", "").strip():
            cv["filter"] = f'"{props["filter"].strip()}"' 
        return cv

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

