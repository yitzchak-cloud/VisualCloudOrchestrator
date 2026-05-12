"""
nodes/resource/pubsub_subscription/_terraform.py
================================================
Terraform variable-building helpers for PubsubSubscriptionNode.
Split from the main node file to keep it readable.

Public API
----------
  make_terraform_call_vars(node_obj, ctx, project, region, all_nodes)
      → dict[str, str]
  terraform_instance_prefix(sub_type: str) → str
"""
from __future__ import annotations

from nodes.base_node import _resource_name, _tf_name, _node_by_id


def terraform_instance_prefix(sub_type: str) -> str:
    return "push_sub" if sub_type == "push" else "pull_sub"


def make_terraform_call_vars(node_obj, ctx, project, region, all_nodes) -> dict:
    node_dict = ctx.get("node", {})
    props     = node_dict.get("props", {})
    sub_type  = props.get("subscription_type", "pull")

    cv: dict = {
        "name":                 f'"{_resource_name(node_dict)}"',
        "ack_deadline_seconds": str(int(props.get("ack_deadline_seconds", 20))),
    }

    # ── Topic reference ───────────────────────────────────────────────────────
    topic_id = ctx.get("topic_id", "")
    cv["topic_name"] = (
        f"module.topic_{_tf_name(_node_by_id(all_nodes, topic_id))}.name"
        if topic_id else '""'
    )

    # ── Filter (both types) ───────────────────────────────────────────────────
    if props.get("filter", "").strip():
        cv["filter"] = f'"{props["filter"].strip()}"'

    if sub_type == "push":
        _add_push_vars(cv, ctx, props, all_nodes)
    else:
        _add_pull_vars(cv, props, ctx, all_nodes)

    return cv


# ── Pull helpers ──────────────────────────────────────────────────────────────

def _add_pull_vars(cv, props, ctx, all_nodes):
    cv["enable_message_ordering"]      = "true" if props.get("enable_message_ordering") else "false"
    cv["enable_exactly_once_delivery"] = "true" if props.get("enable_exactly_once_delivery") else "false"

    dead_letter = props.get("dead_letter_topic", "").strip()
    if dead_letter:
        cv["dead_letter_topic"] = f'"{dead_letter}"'


# ── Push helpers ──────────────────────────────────────────────────────────────

def _add_push_vars(cv, ctx, props, all_nodes):
    push_ids = ctx.get("push_target_ids", [])
    cv["push_endpoint"] = (
        f"module.cr_{_tf_name(_node_by_id(all_nodes, push_ids[0]))}.uri"
        if push_ids
        else f'"{props.get("push_endpoint", "")}"'
    )

    sa_id = ctx.get("service_account_id", "")
    if sa_id:
        cv["oidc_sa_email"] = f"module.sa_{_tf_name(_node_by_id(all_nodes, sa_id))}.email"
    elif props.get("oidc_service_account_email"):
        cv["oidc_sa_email"] = f'"{props["oidc_service_account_email"]}"'
