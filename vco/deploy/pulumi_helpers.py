"""
deploy/pulumi_helpers.py
========================
Low-level Pulumi plumbing — no GCP resources, no business logic:

  _get_pulumi_command(work_dir)   — download/cache the Pulumi CLI binary
  _make_workspace_opts(...)       — build LocalWorkspaceOptions with shared env
  _node_label(nodes, node_id)     — human-readable label for a node id
  _resource_name(node)            — GCP resource name derived from node label/props
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from pulumi import automation as auto

logger = logging.getLogger(__name__)

# Module-level cache — downloaded once per process lifetime
_pulumi_command: "auto.PulumiCommand | None" = None


def get_pulumi_command(work_dir: Path) -> "auto.PulumiCommand":
    """
    Return the Pulumi CLI command object, downloading it if not already cached.
    Binary is stored under  work_dir/.pulumi-cli  so it survives restarts.
    """
    global _pulumi_command
    if _pulumi_command is not None:
        logger.debug("Using cached Pulumi CLI binary")
        return _pulumi_command

    cli_root = work_dir / ".pulumi-cli"
    cli_root.mkdir(parents=True, exist_ok=True)
    logger.info("Installing Pulumi CLI into %s …", cli_root)
    _pulumi_command = auto.PulumiCommand.install(root=str(cli_root))
    logger.info("Pulumi CLI ready")
    return _pulumi_command


def make_workspace_opts(
    work_dir: Path,
    pulumi_command: "auto.PulumiCommand | None" = None,
    backend_url: str | None = None,
    pulumi_home: str | None = None,
) -> auto.LocalWorkspaceOptions:
    """
    Build a LocalWorkspaceOptions that:
      - uses the local file backend (no Pulumi Cloud required)
      - suppresses update-check noise
      - reads PULUMI_CONFIG_PASSPHRASE from the environment
    """
    opts = auto.LocalWorkspaceOptions(
        work_dir=str(work_dir),
        pulumi_home=pulumi_home,
        pulumi_command=pulumi_command,
        env_vars={
            "PULUMI_BACKEND_URL":       backend_url or "",
            "PULUMI_CONFIG_PASSPHRASE": os.environ.get("PULUMI_CONFIG_PASSPHRASE", ""),
            "PULUMI_SKIP_UPDATE_CHECK": "1",
            "PULUMI_ACCESS_TOKEN":      "",
        },
    )
    logger.debug("Workspace opts: work_dir=%s  backend=%s", work_dir, backend_url)
    return opts


def node_label(nodes: list[dict], node_id: str) -> str:
    """Return the human-readable label for *node_id*, falling back to the raw ID."""
    for n in nodes:
        if n["id"] == node_id:
            return n.get("label", node_id)
    return node_id


def resource_name(node: dict) -> str:
    """
    Derive a GCP-safe resource name from the node's props.name or its label.
    Lowercased, non-alphanumeric characters replaced with '-'.
    """
    props = node.get("props", {})
    label = node.get("label", node["id"])
    name  = props.get("name") or re.sub(r"[^a-z0-9-]", "-", label.lower()).strip("-")
    return name

def _destroy_node_stack(node_id, stack_name, work_dir, pulumi_cmd, backend_url, pulumi_home):
    safe_id  = re.sub(r"[^a-zA-Z0-9_]", "-", node_id)
    node_dir = work_dir / safe_id
    if not node_dir.exists():
        return

    stack = auto.select_stack(
        stack_name=f"{stack_name}-{safe_id}",
        project_name="vco-stack",
        program=lambda: None,
        opts=make_workspace_opts(node_dir, pulumi_cmd, backend_url, pulumi_home),
    )
    stack.destroy(on_output=lambda l: logger.info("destroy: %s", l))
    stack.workspace.remove_stack(f"{stack_name}-{safe_id}")
    logger.info("Destroyed orphan stack: %s", node_id)