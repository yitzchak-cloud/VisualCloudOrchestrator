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


    @property
    def terraform_dir(self):
        return Path(__file__).parent / "terraform" / "pubsub_push_subscription"

    @property
    def terraform_instance_prefix(self): return "push_sub"

    def terraform_call_vars(self, ctx, project, region, all_nodes):
        from nodes.base_node import _resource_name, _tf_name, _node_by_id
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        cv = {
            "name":                 f'"{_resource_name(node_dict)}"',
            "ack_deadline_seconds": str(int(props.get("ack_deadline_seconds", 20))),
        }
        topic_id = ctx.get("topic_id", "")
        cv["topic_name"] = f"module.topic_{_tf_name(_node_by_id(all_nodes, topic_id))}.name" if topic_id else '""'
        push_ids = ctx.get("push_target_ids", [])
        cv["push_endpoint"] = f"module.cr_{_tf_name(_node_by_id(all_nodes, push_ids[0]))}.uri" if push_ids else f'"{props.get("push_endpoint","")}"'
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            cv["oidc_sa_email"] = f"module.sa_{_tf_name(_node_by_id(all_nodes, sa_id))}.email"
        elif props.get("oidc_service_account_email"):
            cv["oidc_sa_email"] = f'"{props["oidc_service_account_email"]}"' 
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
