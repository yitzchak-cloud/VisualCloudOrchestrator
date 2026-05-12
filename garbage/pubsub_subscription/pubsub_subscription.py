"""
nodes/resource/pubsub_subscription/pubsub_subscription.py
==========================================================
Unified Pub/Sub Subscription node — replaces the two separate
pubsub_pull_subscription and pubsub_push_subscription nodes.

Design
------
The node type in the YAML graph remains  "PubsubSubscriptionNode".
The *subscription_type* param (pull / push) controls:

  pull → output port "messages" is multi=True   (many consumers can pull)
  push → output port "messages" is multi=False  (one endpoint per sub)

Dynamic port behaviour is driven by the schema flag:
    ports:
      - id: messages
        dynamic_multi: subscription_type  # "pull" → multi, "push" → single

Topology
--------
  PubsubTopicNode ──(SUBSCRIPTION)──► PubsubSubscriptionNode
  PubsubSubscriptionNode ──(MESSAGE)──► CloudRunNode   (push: URI, pull: many)

All params live in params.yaml (loaded via _load_params).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PubsubSubscriptionNode(GCPNode):
    """
    Unified Pub/Sub Subscription.

    Set subscription_type = "pull"  → standard pull subscription (multi-consumer)
    Set subscription_type = "push"  → push subscription (single HTTPS endpoint)

    The "messages" output port is automatically single when push, multi when pull.
    This is declared in the schema via the  dynamic_ports  key so the UI can
    render the correct handle without hard-coding subscription logic.
    """


    # ── Ports ─────────────────────────────────────────────────────────────────
    # The output port multiplicity is declared as dynamic in the schema.
    # The UI reads node.props.subscription_type and renders accordingly.
    # The backend resolve_edges checks it at runtime.
    inputs: ClassVar = [
        Port("topic_link", PortType.SUBSCRIPTION, required=True),
    ]
    outputs: ClassVar = [
        # multi=True is the safe default; for push the UI disables extra edges
        Port("messages", PortType.MESSAGE, multi=True),
    ]

    # ── Visual ────────────────────────────────────────────────────────────────
    node_color:  ClassVar = "#ec485b"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = (
        "Pub/Sub Subscription — pull (multi-consumer) or push (single endpoint). "
        "Select subscription_type to change the output port behaviour."
    )

    # ── Schema metadata for the UI (dynamic port declaration) ─────────────────
    # The UI reads this to know which output port should be limited to 1 edge
    # when subscription_type == "push".
    dynamic_ports: ClassVar = [
        {
            "port":            "messages",
            "multi_when":      {"subscription_type": "pull"},   # multi=True
            "single_when":     {"subscription_type": "push"},   # multi=False
        }
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # Edge wiring
    # ─────────────────────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ── output: subscription → consumer (CloudRun, worker, etc.) ─────────
        if src_id == self.node_id and src_type == "PubsubSubscriptionNode":
            sub_node = ctx.get(self.node_id, {}).get("node", {})
            sub_type = sub_node.get("props", {}).get("subscription_type", "pull")

            if sub_type == "push":
                # push → record single push target
                ctx[self.node_id]["push_target_id"] = tgt_id
            else:
                # pull → any number of consumers
                ctx[self.node_id].setdefault("consumer_ids", []).append(tgt_id)

            ctx[tgt_id].setdefault("receives_from_subs", []).append(self.node_id)
            return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        deps: list[str] = []
        if ctx.get("topic_id"):
            deps.append(ctx["topic_id"])
        # push: wait for target CR so we can read its URI
        push_id = ctx.get("push_target_id")
        if push_id:
            deps.append(push_id)
        return deps

    # ─────────────────────────────────────────────────────────────────────────
    # Pulumi program
    # ─────────────────────────────────────────────────────────────────────────

    def pulumi_program(
        self,
        ctx:              dict[str, Any],
        project:          str,
        region:           str,
        all_nodes:        list[dict],
        deployed_outputs: dict[str, dict],
    ) -> Callable[[], None] | None:

        node_dict  = ctx.get("node", {})
        props      = node_dict.get("props", {})
        sub_type   = props.get("subscription_type", "pull")
        topic_name = deployed_outputs.get(ctx.get("topic_id", ""), {}).get("name", "")

        if not topic_name:
            logger.warning(
                "PubsubSubscriptionNode %s: topic not yet deployed — skipping", self.node_id
            )
            return None

        # ── push: resolve endpoint ─────────────────────────────────────────
        push_endpoint = ""
        if sub_type == "push":
            push_id = ctx.get("push_target_id")
            if push_id and push_id in deployed_outputs:
                push_endpoint = deployed_outputs[push_id].get("uri", "")
            if not push_endpoint:
                push_endpoint = props.get("push_endpoint", "")
            if not push_endpoint:
                logger.warning(
                    "PubsubSubscriptionNode %s (push): no endpoint resolved — skipping",
                    self.node_id,
                )
                return None

        oidc_sa = props.get("oidc_service_account_email", "")

        def program() -> None:
            common = dict(
                name=_resource_name(node_dict),
                topic=topic_name,
                ack_deadline_seconds=int(props.get("ack_deadline_seconds", 20)),
                project=project,
            )

            if sub_type == "push":
                sub = gcp.pubsub.Subscription(
                    self.node_id,
                    **common,
                    push_config=gcp.pubsub.SubscriptionPushConfigArgs(
                        push_endpoint=push_endpoint,
                        oidc_token=(
                            gcp.pubsub.SubscriptionPushConfigOidcTokenArgs(
                                service_account_email=oidc_sa,
                            ) if oidc_sa else None
                        ),
                    ),
                )
            else:
                sub = gcp.pubsub.Subscription(
                    self.node_id,
                    **common,
                    enable_message_ordering=bool(props.get("enable_message_ordering", False)),
                    enable_exactly_once_delivery=bool(props.get("enable_exactly_once_delivery", False)),
                )

            pulumi.export("name", sub.name)
            pulumi.export("id",   sub.id)

        return program

    # ─────────────────────────────────────────────────────────────────────────
    # Terraform static-module interface
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return "sub"

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        from nodes.base_node import _resource_name, _tf_name, _node_by_id
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        sub_type  = props.get("subscription_type", "pull")

        cv: dict[str, str] = {
            "name":                 f'"{_resource_name(node_dict)}"',
            "subscription_type":    f'"{sub_type}"',
            "ack_deadline_seconds": str(int(props.get("ack_deadline_seconds", 20))),
            "enable_message_ordering":      "true" if props.get("enable_message_ordering") else "false",
            "enable_exactly_once_delivery": "true" if props.get("enable_exactly_once_delivery") else "false",
        }

        topic_id = ctx.get("topic_id", "")
        cv["topic_name"] = (
            f"module.topic_{_tf_name(_node_by_id(all_nodes, topic_id))}.name"
            if topic_id else '""'
        )

        # push endpoint
        push_id = ctx.get("push_target_id", "")
        if push_id:
            cv["push_endpoint"] = (
                f"module.cr_{_tf_name(_node_by_id(all_nodes, push_id))}.uri"
            )
        elif props.get("push_endpoint"):
            cv["push_endpoint"] = f'"{props["push_endpoint"]}"'
        else:
            cv["push_endpoint"] = '""'

        # OIDC SA
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            cv["oidc_sa_email"] = f"module.sa_{_tf_name(_node_by_id(all_nodes, sa_id))}.email"
        elif props.get("oidc_service_account_email"):
            cv["oidc_sa_email"] = f'"{props["oidc_service_account_email"]}"'
        else:
            cv["oidc_sa_email"] = '""'

        if props.get("filter", "").strip():
            cv["filter"] = f'"{props["filter"].strip()}"'
        else:
            cv["filter"] = '""'

        return cv

    # ─────────────────────────────────────────────────────────────────────────
    # Post-deploy
    # ─────────────────────────────────────────────────────────────────────────

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
