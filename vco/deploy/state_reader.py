"""
deploy/state_reader.py
======================
Reads the live deployed state directly from Pulumi stacks on disk.
This is the single source of truth — no separate actual.yaml needed.

  read_actual_state(work_dir, stack) -> {
      "node_ids": [...],
      "nodes": {
          "<node_id>": {
              "status":       "deployed" | "failed" | "unknown",
              "outputs":      {"uri": "...", "name": "...", ...},
              "last_updated": "2024-01-01T12:00:00" | None,
          },
          ...
      }
  }
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from pulumi import automation as auto

from deploy.pulumi_helpers import get_pulumi_command

logger = logging.getLogger(__name__)


def read_actual_state(work_dir: str, stack: str = "dev") -> dict:
    """
    Walk every per-node subdirectory under *work_dir*, open its Pulumi stack,
    and collect outputs + last update result.

    Directories starting with '.' are skipped (they're internal Pulumi dirs).
    Dirs that have no Pulumi stack yet (never deployed) are silently skipped.
    """
    stack_dir = Path(work_dir)
    if not stack_dir.exists():
        logger.info("state_reader: work_dir %s does not exist — empty state", stack_dir)
        return {"node_ids": [], "nodes": {}}

    state_dir   = (stack_dir / ".pulumi-state").resolve()
    pulumi_home = str((stack_dir / ".pulumi-home").resolve())
    backend_url = os.environ.get(
        "PULUMI_BACKEND_URL",
        "file://" + state_dir.as_posix(),
    )

    if not state_dir.exists():
        logger.info("state_reader: no Pulumi state dir found at %s", state_dir)
        return {"node_ids": [], "nodes": {}}

    shared_env = {
        "PULUMI_BACKEND_URL":       backend_url,
        "PULUMI_CONFIG_PASSPHRASE": os.environ.get("PULUMI_CONFIG_PASSPHRASE", ""),
        "PULUMI_SKIP_UPDATE_CHECK": "1",
        "PULUMI_ACCESS_TOKEN":      "",
        "PULUMI_HOME":              pulumi_home,
    }

    result: dict = {"node_ids": [], "nodes": {}}

    for node_dir in sorted(stack_dir.iterdir()):
        if not node_dir.is_dir() or node_dir.name.startswith("."):
            continue

        safe_id   = node_dir.name
        full_name = f"{stack}-{safe_id}"
        node_id   = safe_id   # IDs are already the canonical form

        logger.debug("state_reader: reading stack %s from %s", full_name, node_dir)

        try:
            cmd = get_pulumi_command(stack_dir)
            stack_obj = auto.create_or_select_stack(
                stack_name=full_name,
                project_name="vco-stack",
                program=lambda: None,   # dummy — read-only
                opts=auto.LocalWorkspaceOptions(
                    work_dir=str(node_dir),
                    pulumi_home=pulumi_home,
                    pulumi_command=cmd,
                    env_vars=shared_env,
                ),
            )

            outputs = {k: v.value for k, v in stack_obj.outputs().items()}
            history = stack_obj.history(page_size=1)
            last    = history[0] if history else None

            status       = "unknown"
            last_updated = None

            if last:
                last_updated = last.end_time.isoformat() if last.end_time else None
                if last.result == "succeeded":
                    status = "deployed"
                elif last.result == "failed":
                    status = "failed"

            result["node_ids"].append(node_id)
            result["nodes"][node_id] = {
                "status":       status,
                "outputs":      outputs,
                "last_updated": last_updated,
            }
            logger.debug("state_reader: %s → status=%s  outputs=%s", node_id, status, list(outputs.keys()))

        except Exception as exc:
            logger.debug("state_reader: skipping %s — %s", safe_id, exc)
            continue

    logger.info(
        "state_reader: found %d deployed nodes: %s",
        len(result["node_ids"]), result["node_ids"],
    )
    return result
