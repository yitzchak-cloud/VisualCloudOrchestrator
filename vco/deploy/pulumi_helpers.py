"""
deploy/pulumi_helpers.py
========================
Low-level Pulumi plumbing — no GCP resources, no business logic.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from pulumi import automation as auto

logger = logging.getLogger(__name__)

_pulumi_command: "auto.PulumiCommand | None" = None

def get_pulumi_command(work_dir: Path) -> "auto.PulumiCommand":
    global _pulumi_command
    if _pulumi_command is not None:
        return _pulumi_command
    cli_root = work_dir.resolve() / ".pulumi-cli" 
    cli_root.mkdir(parents=True, exist_ok=True)
    logger.info("Installing Pulumi CLI into %s …", cli_root)
    _pulumi_command = auto.PulumiCommand.install(root=str(cli_root))
    logger.info("Pulumi CLI ready")
    return _pulumi_command

def make_workspace_opts(
    work_dir:       Path,
    pulumi_command: "auto.PulumiCommand | None" = None,
    backend_url:    str | None = None,
    pulumi_home:    str | None = None,
) -> auto.LocalWorkspaceOptions:
    return auto.LocalWorkspaceOptions(
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


def node_label(nodes: list[dict], node_id: str) -> str:
    for n in nodes:
        if n["id"] == node_id:
            return n.get("label", node_id)
    return node_id


def resource_name(node: dict) -> str:
    props = node.get("props", {})
    label = node.get("label", node["id"])
    name  = props.get("name") or re.sub(r"[^a-z0-9-]", "-", label.lower()).strip("-")
    return name


def _destroy_node_stack(
    node_id:     str,
    stack_name:  str,
    work_dir:    Path,
    pulumi_cmd:  "auto.PulumiCommand",
    backend_url: str,
    pulumi_home: str,
) -> None:
    """
    Destroy a node's Pulumi stack and remove all traces from disk.

    Two bugs fixed vs the original:
      1. After destroy(), the node directory was left on disk.
         state_reader would re-discover it on every deploy → infinite orphan loop.
         Fix: shutil.rmtree the directory after a successful destroy.

      2. If the stack had no resources (already empty / previously failed),
         destroy() would raise. We catch that and still remove the directory.
    """
    safe_id  = re.sub(r"[^a-zA-Z0-9_]", "-", node_id)
    node_dir = work_dir / safe_id

    if not node_dir.exists():
        logger.debug("_destroy_node_stack: %s — directory not found, nothing to do", node_id)
        return

    full_stack_name = f"{stack_name}-{safe_id}"

    try:
        stack = auto.select_stack(
            stack_name=full_stack_name,
            project_name="vco-stack",
            program=lambda: None,
            opts=make_workspace_opts(node_dir, pulumi_cmd, backend_url, pulumi_home),
        )

        # Check if there are any live resources before destroying
        # (avoids a noisy error when the stack is already empty)
        try:
            summary = stack.export_stack()
            has_resources = bool(
                summary.deployment
                and summary.deployment.get("resources")
                # Pulumi always has a "pulumi:pulumi:Stack" pseudo-resource
                and len(summary.deployment["resources"]) > 1
            )
        except Exception:
            has_resources = True  # assume yes and let destroy decide

        if has_resources:
            logger.info("_destroy_node_stack: destroying GCP resources for %s …", node_id)
            stack.destroy(on_output=lambda line: logger.info("destroy [%s]: %s", safe_id, line))
        else:
            logger.info("_destroy_node_stack: %s stack is already empty, skipping destroy", node_id)

        # Remove the Pulumi stack record from the backend
        try:
            stack.workspace.remove_stack(full_stack_name)
            logger.info("_destroy_node_stack: removed stack record %s", full_stack_name)
        except Exception as exc:
            logger.debug("_destroy_node_stack: remove_stack warning — %s", exc)

    except Exception as exc:
        logger.warning(
            "_destroy_node_stack: could not select/destroy stack %s — %s. "
            "Will still remove directory.",
            full_stack_name, exc,
        )

    # ── Always remove the directory from disk ─────────────────────────────────
    # This is the critical fix: without this, state_reader re-discovers the
    # directory on every deploy and adds it back to the orphan list forever.
    try:
        shutil.rmtree(node_dir)
        logger.info("_destroy_node_stack: removed directory %s", node_dir)
    except Exception as exc:
        logger.error("_destroy_node_stack: could not remove %s — %s", node_dir, exc)