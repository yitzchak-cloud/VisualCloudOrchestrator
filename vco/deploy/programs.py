"""
deploy/programs.py
==================
One factory function per GCP resource type.
Each factory captures its arguments in a closure and returns a  () -> None
that Pulumi's Automation API calls inside the stack runtime.

Adding a new resource type:
  1. Write a new  _program_<type>(node, project, …) -> Callable[[], None]
  2. Register it in  build_program()  at the bottom of this file.

Exports (what downstream nodes can read from deployed_outputs[node_id]):
  PubsubTopicNode          → name, id
  CloudRunNode             → uri, name, id
  PubsubPullSubscription   → name, id
  PubsubPushSubscription   → name, id
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import pulumi
import pulumi_gcp as gcp

from deploy.pulumi_helpers import node_label, resource_name

logger = logging.getLogger(__name__)


# ── PubSub Topic ──────────────────────────────────────────────────────────────

def _program_topic(node: dict, project: str) -> Callable[[], None]:
    def program() -> None:
        props = node.get("props", {})
        logger.debug("[program] Creating PubSub Topic: %s", resource_name(node))
        t = gcp.pubsub.Topic(
            node["id"],
            name=resource_name(node),
            message_retention_duration=props.get("message_retention_duration", "604800s"),
            project=project,
        )
        pulumi.export("name", t.name)
        pulumi.export("id",   t.id)
    return program


# ── Cloud Run ─────────────────────────────────────────────────────────────────

def _program_cloud_run(
    node:          dict,
    project:       str,
    region:        str,
    all_nodes:     list[dict],
    topic_outputs: dict[str, dict],   # node_id → {"name": Output[str], …}
    sub_names:     dict[str, str],    # node_id → plain resource name str
) -> Callable[[], None]:
    def program() -> None:
        props = node.get("props", {})
        envs: list[gcp.cloudrunv2.ServiceTemplateContainerEnvArgs] = []

        # Inject topic names as env vars (PUBSUB_TOPIC_<LABEL>)
        for topic_id, t_out in topic_outputs.items():
            env_key = "PUBSUB_TOPIC_" + re.sub(
                r"[^A-Z0-9]", "_", node_label(all_nodes, topic_id).upper()
            )
            envs.append(gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name=env_key,
                value=t_out["name"],
            ))
            logger.debug("[program] CR env: %s = <topic Output>", env_key)

        # Inject subscription names as env vars (PUBSUB_SUBSCRIPTION_<LABEL>)
        for sub_id, sub_name in sub_names.items():
            env_key = "PUBSUB_SUBSCRIPTION_" + re.sub(
                r"[^A-Z0-9]", "_", node_label(all_nodes, sub_id).upper()
            )
            envs.append(gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name=env_key,
                value=sub_name,
            ))
            logger.debug("[program] CR env: %s = %s", env_key, sub_name)

        logger.debug("[program] Creating Cloud Run: %s  image=%s", resource_name(node), props.get("image"))

        svc = gcp.cloudrunv2.Service(
            node["id"],
            name=resource_name(node),
            location=region,
            project=project,
            deletion_protection=False,
            # Org Policy compliance:
            #   ingress = internal only  (no public traffic)
            #   egress  = all-traffic    (required by org policy)
            #   invoker = IAM-authenticated only (no allUsers)
            ingress="INGRESS_TRAFFIC_INTERNAL_ONLY",
            template=gcp.cloudrunv2.ServiceTemplateArgs(
                containers=[gcp.cloudrunv2.ServiceTemplateContainerArgs(
                    image=props.get("image", "gcr.io/cloudrun/hello"),
                    envs=envs or None,
                )],
                vpc_access=gcp.cloudrunv2.ServiceTemplateVpcAccessArgs(
                    egress="PRIVATE_RANGES_ONLY",
                    network_interfaces=[
                        gcp.cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=props.get(
                                "vpc_network",
                                "projects/hrz-endor-net-0/global/networks/endor-0",
                            ),
                            subnetwork=props.get(
                                "vpc_subnetwork",
                                "projects/hrz-endor-net-0/regions/me-west1/subnetworks/endor-1-subnet",
                            ),
                        )
                    ],
                ),
            ),
        )
        pulumi.export("uri",  svc.uri)
        pulumi.export("name", svc.name)
        pulumi.export("id",   svc.id)
    return program


# ── PubSub Pull Subscription ──────────────────────────────────────────────────

def _program_pull_subscription(
    node:       dict,
    project:    str,
    topic_name: Any,   # Output[str]
) -> Callable[[], None]:
    def program() -> None:
        props = node.get("props", {})
        logger.debug("[program] Creating PullSubscription: %s", resource_name(node))
        sub = gcp.pubsub.Subscription(
            node["id"],
            name=resource_name(node),
            topic=topic_name,
            ack_deadline_seconds=props.get("ack_deadline_seconds", 20),
            project=project,
        )
        pulumi.export("name", sub.name)
        pulumi.export("id",   sub.id)
    return program


# ── PubSub Push Subscription ──────────────────────────────────────────────────

def _program_push_subscription(
    node:          dict,
    project:       str,
    topic_name:    Any,   # Output[str]
    push_endpoint: Any,   # Output[str] or plain str
) -> Callable[[], None]:
    def program() -> None:
        props   = node.get("props", {})
        oidc_sa = props.get("oidc_service_account_email", "")
        logger.debug(
            "[program] Creating PushSubscription: %s  endpoint=%s",
            resource_name(node), push_endpoint,
        )
        sub = gcp.pubsub.Subscription(
            node["id"],
            name=resource_name(node),
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


# ── Public dispatcher ─────────────────────────────────────────────────────────

def build_program(
    node:             dict,
    ntype:            str,
    nc:               dict,             # node context from resolve_graph
    project:          str,
    region:           str,
    all_nodes:        list[dict],
    deployed_outputs: dict[str, dict],  # live outputs from already-deployed nodes
) -> Callable[[], None] | None:
    """
    Select and construct the right Pulumi program for *node*.
    Returns None if the node type is unknown or dependencies are not yet deployed.

    Callers should treat None as "skip this node" and log accordingly.
    """
    if ntype == "PubsubTopicNode":
        return _program_topic(node, project)

    if ntype == "CloudRunNode":
        t_outputs = {
            tid: deployed_outputs[tid]
            for tid in nc.get("publishes_to_topics", [])
            if tid in deployed_outputs
        }
        s_names = {
            sid: resource_name(next(n for n in all_nodes if n["id"] == sid))
            for sid in nc.get("receives_from_subs", [])
            if any(n["id"] == sid for n in all_nodes)
        }
        return _program_cloud_run(node, project, region, all_nodes, t_outputs, s_names)

    if ntype == "PubsubPullSubscriptionNode":
        topic_id  = nc.get("topic_id")
        topic_out = deployed_outputs.get(topic_id, {}) if topic_id else {}
        topic_name = topic_out.get("name", "")
        if not topic_name:
            logger.warning("build_program: topic not deployed yet for PullSub %s — skipping", node["id"])
            return None
        return _program_pull_subscription(node, project, topic_name)

    if ntype == "PubsubPushSubscriptionNode":
        topic_id  = nc.get("topic_id")
        topic_out = deployed_outputs.get(topic_id, {}) if topic_id else {}
        topic_name = topic_out.get("name", "")
        if not topic_name:
            logger.warning("build_program: topic not deployed yet for PushSub %s — skipping", node["id"])
            return None
        push_cr_ids = nc.get("push_target_cr_ids", [])
        push_endpoint = (
            deployed_outputs[push_cr_ids[0]].get("uri", "")
            if push_cr_ids and push_cr_ids[0] in deployed_outputs
            else node.get("props", {}).get("push_endpoint", "")
        )
        return _program_push_subscription(node, project, topic_name, push_endpoint)

    logger.warning("build_program: unknown node type '%s' — skipping", ntype)
    return None
