"""
nodes/resource/notification_channel/_terraform.py
==================================================
Terraform call-vars factory for NotificationChannelNode.

Note: Terraform support covers the notification channel resource itself.
The alert policy binding is emitted as a separate module call derived
from the source_type stored in ctx.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from nodes.base_node import _tf_name

if TYPE_CHECKING:
    from nodes.resource.notification_channel.notification_channel import NotificationChannelNode

logger = logging.getLogger(__name__)

_GCP_CHANNEL_TYPE: dict[str, str] = {
    "email":      "email",
    "slack":      "slack",
    "pagerduty":  "pagerduty",
    "webhook":    "webhook_tokenauth",
    "pubsub":     "pubsub",
}


def terraform_instance_prefix(mode: str = "") -> str:
    return "notif_ch"


def make_terraform_call_vars(
    node:      "NotificationChannelNode",
    ctx:       dict[str, Any],
    project:   str,
    region:    str,
    all_nodes: list[dict],
) -> dict[str, str]:
    node_dict    = ctx.get("node", {})
    props        = node_dict.get("props", {})
    source_type  = ctx.get("source_type", "")

    display_name = props.get("name") or _tf_name(node_dict)
    channel_type = props.get("channel_type", "email")
    gcp_type     = _GCP_CHANNEL_TYPE.get(channel_type, "email")

    if not display_name:
        logger.warning("NotificationChannelNode %s: missing name — skipped", node.node_id)
        return {}

    # Build labels JSON string for Terraform
    labels = _build_labels_hcl(channel_type, props)

    return {
        "display_name": f'"{display_name}"',
        "channel_type": f'"{gcp_type}"',
        "labels":       labels,
        "source_type":  f'"{source_type}"',
        "project_id":   f'"{project}"',
    }


def _build_labels_hcl(channel_type: str, props: dict) -> str:
    """Return an HCL map literal string for the labels variable."""
    if channel_type == "email":
        addr = props.get("email_address", "")
        return f'{{ email_address = "{addr}" }}'
    if channel_type == "slack":
        ch  = props.get("slack_channel_name", "")
        tok = props.get("slack_auth_token", "")
        return f'{{ channel_name = "{ch}", auth_token = "{tok}" }}'
    if channel_type == "pagerduty":
        key = props.get("pagerduty_service_key", "")
        return f'{{ service_key = "{key}" }}'
    if channel_type == "webhook":
        url = props.get("webhook_url", "")
        usr = props.get("webhook_username", "")
        pwd = props.get("webhook_password", "")
        parts = [f'url = "{url}"']
        if usr:
            parts.append(f'username = "{usr}"')
        if pwd:
            parts.append(f'password = "{pwd}"')
        return "{ " + ", ".join(parts) + " }"
    if channel_type == "pubsub":
        topic = props.get("pubsub_topic", "")
        return f'{{ topic = "{topic}" }}'
    return "{}"
