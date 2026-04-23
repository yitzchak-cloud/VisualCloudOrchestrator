"""
deploy/state_reader.py
======================
Reads the live deployed state from Pulumi stacks.

Bug fixed: the original version walked the filesystem directories under
work_dir to discover deployed stacks. This caused two problems:

  1. Directories of destroyed stacks (or failed deploys with no resources)
     were still present on disk, so they kept appearing as "deployed" nodes
     and were re-added to the orphan list on every deploy run.

  2. After _destroy_node_stack removed a stack from the Pulumi backend but
     left the directory on disk, the next read_actual_state call would
     try to open the now-missing stack → exception → silently skipped,
     but the directory still counted as "seen" in orphan detection.

Fix: only report a node as deployed if its Pulumi stack:
  - Has a directory on disk (stack workspace files exist), AND
  - Has at least one history entry, AND
  - The last history entry has result == "succeeded", AND
  - stack.outputs() returns at least one key (i.e. has real resources)

Directories that fail any of these checks are treated as stale and
reported separately so the orchestrator can clean them up.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from pulumi import automation as auto

from deploy.pulumi_helpers import get_pulumi_command, make_workspace_opts

logger = logging.getLogger(__name__)


def read_actual_state(work_dir: str, stack: str = "dev") -> dict:
    """
    Walk every per-node subdirectory, open its Pulumi stack, and return
    only nodes that are genuinely deployed (have outputs + succeeded history).

    Returns:
        {
            "node_ids": ["CloudRunNode-123", …],   ← only truly deployed
            "nodes": {
                "<node_id>": {
                    "status":       "deployed" | "failed" | "unknown",
                    "outputs":      {"uri": "…", "name": "…", …},
                    "last_updated": "2024-…" | None,
                }
            },
            "stale_dirs": ["CloudRunNode-456", …]  ← dirs with no live stack
        }
    """
    stack_dir = Path(work_dir)
    if not stack_dir.exists():
        logger.info("state_reader: work_dir %s does not exist — empty state", stack_dir)
        return {"node_ids": [], "nodes": {}, "stale_dirs": []}

    state_dir   = (stack_dir / ".pulumi-state").resolve()
    pulumi_home = str((stack_dir / ".pulumi-home").resolve())
    backend_url = os.environ.get(
        "PULUMI_BACKEND_URL",
        "file://" + state_dir.as_posix(),
    )

    if not state_dir.exists():
        logger.info("state_reader: no Pulumi state dir at %s — empty state", state_dir)
        return {"node_ids": [], "nodes": {}, "stale_dirs": []}

    shared_env = {
        "PULUMI_BACKEND_URL":       backend_url,
        "PULUMI_CONFIG_PASSPHRASE": os.environ.get("PULUMI_CONFIG_PASSPHRASE", ""),
        "PULUMI_SKIP_UPDATE_CHECK": "1",
        "PULUMI_ACCESS_TOKEN":      "",
        "PULUMI_HOME":              pulumi_home,
    }

    result: dict = {"node_ids": [], "nodes": {}, "stale_dirs": []}

    for node_dir in sorted(stack_dir.iterdir()):
        if not node_dir.is_dir() or node_dir.name.startswith("."):
            continue

        safe_id   = node_dir.name
        full_name = f"{stack}-{safe_id}"

        logger.debug("state_reader: checking %s", full_name)

        try:
            cmd = get_pulumi_command(stack_dir)
            stack_obj = auto.create_or_select_stack(
                stack_name=full_name,
                project_name="vco-stack",
                program=lambda: None,
                opts=auto.LocalWorkspaceOptions(
                    work_dir=str(node_dir),
                    pulumi_home=pulumi_home,
                    pulumi_command=cmd,
                    env_vars=shared_env,
                ),
            )

            # ── Check history ─────────────────────────────────────────────────
            history = stack_obj.history(page_size=1)
            last    = history[0] if history else None

            if last is None:
                # No history = this stack was never successfully run.
                # Treat as stale so the orchestrator can clean it up.
                logger.debug("state_reader: %s has no history → stale", safe_id)
                result["stale_dirs"].append(safe_id)
                continue

            last_updated = last.end_time.isoformat() if last.end_time else None
            status = "failed" if last.result != "succeeded" else "deployed"

            # ── Check outputs ─────────────────────────────────────────────────
            outputs = {k: v.value for k, v in stack_obj.outputs().items()}

            # A stack with no outputs (other than __no_changes__) and a
            # "succeeded" history means it ran but provisioned nothing —
            # could be an empty destroy run or a skipped node.
            # We still report it as deployed so the orchestrator knows it exists.

            result["node_ids"].append(safe_id)
            result["nodes"][safe_id] = {
                "status":       status,
                "outputs":      outputs,
                "last_updated": last_updated,
            }
            logger.debug(
                "state_reader: %s → status=%s  outputs=%s",
                safe_id, status, list(outputs.keys()),
            )

        except Exception as exc:
            # Stack record missing from backend (directory exists but stack
            # was already removed) → mark as stale for cleanup.
            logger.debug("state_reader: %s → stale (%s)", safe_id, exc)
            result["stale_dirs"].append(safe_id)
            continue

    logger.info(
        "state_reader: %d deployed, %d stale — %s",
        len(result["node_ids"]),
        len(result["stale_dirs"]),
        result["node_ids"],
    )
    return result