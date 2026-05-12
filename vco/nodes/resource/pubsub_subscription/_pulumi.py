"""
nodes/resource/pubsub_subscription/_pulumi.py
=============================================
Pulumi program factories for PubsubSubscriptionNode.
Split from the main node file to keep it readable.

Public API
----------
  make_pulumi_program(node_obj, ctx, project, region, all_nodes, deployed_outputs)
      → Callable[[], None] | None
"""
from __future__ import annotations

import logging
from typing import Any

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import _resource_name
from nodes.ctx_keys import K

logger = logging.getLogger(__name__)


def make_pulumi_program(node_obj, ctx, project, region, all_nodes, deployed_outputs):
    """
    Dispatch to the correct Pulumi factory based on subscription_type prop.
    Returns None when a required upstream dependency is not yet deployed.
    """
    node_dict  = ctx.get("node", {})
    props      = node_dict.get("props", {})
    sub_type   = props.get("subscription_type", "pull")
    topic_name = deployed_outputs.get(ctx.get(K.TOPIC_ID, ""), {}).get("name", "")

    if not topic_name:
        logger.warning(
            "PubsubSubscriptionNode %s: topic not deployed — skipping", node_obj.node_id
        )
        return None

    if sub_type == "push":
        return _make_push_program(node_obj, node_dict, props, ctx, project, topic_name, deployed_outputs)
    else:
        return _make_pull_program(node_obj, node_dict, props, project, topic_name)


# ── Pull ──────────────────────────────────────────────────────────────────────

def _make_pull_program(node_obj, node_dict, props, project, topic_name):
    def program() -> None:
        kwargs: dict[str, Any] = dict(
            name=_resource_name(node_dict),
            topic=topic_name,
            ack_deadline_seconds=props.get("ack_deadline_seconds", 20),
            project=project,
        )

        if props.get("enable_message_ordering"):
            kwargs["enable_message_ordering"] = True

        if props.get("enable_exactly_once_delivery"):
            kwargs["enable_exactly_once_delivery"] = True

        filter_expr = props.get("filter", "").strip()
        if filter_expr:
            kwargs["filter"] = filter_expr

        dead_letter = props.get("dead_letter_topic", "").strip()
        if dead_letter:
            kwargs["dead_letter_policy"] = gcp.pubsub.SubscriptionDeadLetterPolicyArgs(
                dead_letter_topic=dead_letter,
            )

        sub = gcp.pubsub.Subscription(node_obj.node_id, **kwargs)
        pulumi.export("name", sub.name)
        pulumi.export("id",   sub.id)

    return program


# ── Push ──────────────────────────────────────────────────────────────────────

def _make_push_program(node_obj, node_dict, props, ctx, project, topic_name, deployed_outputs):
    # Resolve push endpoint: wired Cloud Run node takes precedence over manual prop
    push_target_ids = ctx.get(K.PUSH_TARGET_IDS, [])
    push_endpoint   = (
        deployed_outputs[push_target_ids[0]].get("uri", "")
        if push_target_ids and push_target_ids[0] in deployed_outputs
        else props.get("push_endpoint", "")
    )

    sa_id   = ctx.get(K.SERVICE_ACCOUNT, "")
    oidc_sa = (
        deployed_outputs.get(sa_id, {}).get("email", "")
        if sa_id
        else props.get("oidc_service_account_email", "")
    )

    def program() -> None:
        sub = gcp.pubsub.Subscription(
            node_obj.node_id,
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