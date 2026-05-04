"""
deploy/stack_runner.py
======================
Runs a single node's Pulumi stack (preview → up) in a thread-pool executor.

  run_node_stack(node_id, program, …) → dict[str, Any]

The function is synchronous (blocking) and is designed to be called via
  asyncio.get_event_loop().run_in_executor(None, run_node_stack, …)
so it never blocks the FastAPI event loop.

Return value keys:
  __no_changes__  : bool    (True when preview showed nothing to do)
  <output_key>    : Any     (Pulumi stack exports, e.g. uri, name, id)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from matplotlib.pylab import stack
from pulumi import automation as auto
from pulumi.automation.events import OpType

from deploy.pulumi_helpers import get_pulumi_command, make_workspace_opts

logger = logging.getLogger(__name__)


def run_node_stack(
    node_id:        str,
    program:        Callable[[], None],
    stack_name:     str,
    work_dir:       Path,
    project:        str,
    region:         str,
    on_output:      Callable[[str], None],
    pulumi_command: "auto.PulumiCommand | None" = None,
    backend_url:    str = "",
    pulumi_home:    str = "",
) -> dict[str, Any]:
    """
    Create-or-select a Pulumi stack for *node_id*, preview, and (if there are
    changes) run  stack.up().

    Stack name: <stack_name>-<safe_node_id>
    Stack dir:  work_dir/<safe_node_id>/

    All nodes share the same backend_url + pulumi_home so state lives in one
    place and the Pulumi login happens only once.
    """
    safe_id   = re.sub(r"[^a-zA-Z0-9_]", "-", node_id)
    full_name = f"{stack_name}-{safe_id}"
    node_dir  = work_dir / safe_id
    node_dir.mkdir(parents=True, exist_ok=True)

    logger.info("stack_runner: selecting stack %s  dir=%s", full_name, node_dir)

    stack = auto.create_or_select_stack(
        stack_name=full_name,
        project_name="vco-stack",
        program=program,
        opts=make_workspace_opts(node_dir, pulumi_command, backend_url, pulumi_home),
    )
    stack.set_config("gcp:project", auto.ConfigValue(value=project))
    stack.set_config("gcp:region",  auto.ConfigValue(value=region))

    # ── דלג על preview — קורא ל-compute.googleapis.com שחסום ─────────────
    logger.info("stack_runner: running up() for %s", full_name)
    result = stack.up(on_output=on_output, color="never", continue_on_error=True)
    
    outputs = {k: v.value for k, v in result.outputs.items()}
    
    # בדוק אם היו שינויים
    resource_changes = result.summary.resource_changes or {}
    change_ops = {op for op, count in resource_changes.items() if count > 0}
    has_changes = bool(change_ops - {OpType.SAME})
    
    if not has_changes:
        return {"__no_changes__": True, **outputs}
    
    logger.info("stack_runner: up() complete for %s  outputs=%s", full_name, list(outputs.keys()))
    return outputs