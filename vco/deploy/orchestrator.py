"""
deploy/orchestrator.py
======================
Top-level async entry points consumed by the FastAPI routes.

After every successful node deploy, the orchestrator:
  1. Calls  node.live_outputs()  to map Pulumi exports → UI props.
  2. Broadcasts a  node_props_update  WS event so the frontend can
     update the canvas node (e.g. write the real service_url back
     into the Cloud Run card) without a page reload.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from pulumi import automation as auto

from deploy.graph_resolver import build_dag, resolve_graph
from deploy.programs import build_program
from deploy.pulumi_helpers import get_pulumi_command, node_label, _destroy_node_stack
from deploy.stack_runner import run_node_stack
from deploy.state_reader import read_actual_state

logger = logging.getLogger(__name__)

_SIG_WORKING   = "__node_working__"
_SIG_DEPLOYED  = "__node_deployed__"
_SIG_FAILED    = "__node_failed__"
_SIG_NO_CHANGE = "__node_no_change__"


def _classify_line(line: str) -> str:
    low = line.lower()
    if any(w in low for w in ("error", "failed", "panic")):
        return "error"
    if "warning" in low:
        return "warn"
    if any(c in line for c in ("+ ", "created", "updated")):
        return "ok"
    return "info"


def _install_gcp_plugin(stack_dir: Path) -> tuple[Any, str, str]:
    cmd       = get_pulumi_command(stack_dir)
    state_dir = (stack_dir / ".pulumi-state").resolve()
    b_url     = os.environ.get("PULUMI_BACKEND_URL", "file://" + state_dir.as_posix())
    p_home    = str((stack_dir / ".pulumi-home").resolve())

    state_dir.mkdir(parents=True, exist_ok=True)
    (stack_dir / ".pulumi-home").mkdir(parents=True, exist_ok=True)

    shared_env = {
        "PULUMI_BACKEND_URL":       b_url,
        "PULUMI_CONFIG_PASSPHRASE": os.environ.get("PULUMI_CONFIG_PASSPHRASE", ""),
        "PULUMI_SKIP_UPDATE_CHECK": "1",
        "PULUMI_ACCESS_TOKEN":      "",
        "PULUMI_HOME":              p_home,
    }
    cmd.run(["login", b_url], cwd=str(stack_dir), additional_env=shared_env)
    ws = auto.LocalWorkspace(
        work_dir=str(stack_dir), pulumi_home=p_home,
        env_vars=shared_env, pulumi_command=cmd,
    )
    ws.install_plugin("gcp", "v7")
    return cmd, b_url, p_home


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_node_instance(node: dict, node_registry: dict):
    """Instantiate a GCPNode from the registry, or return None."""
    cls = node_registry.get(node.get("type", ""))
    return cls(node_id=node["id"], label=node.get("label", "")) if cls else None


# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_and_deploy(
    nodes:         list[dict],
    edges:         list[dict],
    project:       str,
    region:        str = "us-central1",
    stack:         str = "dev",
    log:           Callable[[str, str, str | None], Any] | None = None,
    work_dir:      str | None = None,
    node_registry: dict | None = None,
    ws_manager=None,   # core.ws_manager.manager — optional for node_props_update
) -> dict:
    """
    Full deploy pipeline.

    After each node is deployed, broadcasts:
      - node_status        (deployed / failed / no_change)
      - node_props_update  (live URL, resource name, etc.) — via ws_manager
    """
    if node_registry is None:
        from core.registry import NODE_REGISTRY
        node_registry = NODE_REGISTRY

    async def _log(msg: str, level: str = "info", node_id: str | None = None) -> None:
        if log:
            await log(msg, level, node_id)

    stack_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="vco_pulumi_"))
    stack_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    # ── Phase 1 ───────────────────────────────────────────────────────────────
    await _log("Phase 1 — Analysing graph dependencies…")
    ctx = resolve_graph(nodes, edges, node_registry)

    try:
        order = build_dag(nodes, ctx, node_registry)
    except ValueError as exc:
        await _log(str(exc), "error")
        return {"status": "error", "phase": "dag", "output": str(exc)}

    by_id = {n["id"]: n for n in nodes}
    order_labels = " → ".join(node_label(nodes, nid) for nid in order)
    await _log(f"Deployment order ({len(order)} nodes): {order_labels}")

    # ── Phase 2 ───────────────────────────────────────────────────────────────
    await _log("Phase 2 — Installing Pulumi GCP plugin…")
    try:
        pulumi_cmd, backend_url, pulumi_home = await loop.run_in_executor(
            None, _install_gcp_plugin, stack_dir
        )
    except Exception as exc:
        await _log(f"Plugin install failed: {exc}", "error")
        return {"status": "error", "phase": "plugin", "output": str(exc)}

    # ── Phase 2.5: destroy orphans ────────────────────────────────────────────
    desired_ids = {n["id"] for n in nodes}
    actual      = read_actual_state(str(stack_dir), stack)
    orphans     = [nid for nid in actual["node_ids"] if nid not in desired_ids]
    if orphans:
        await _log(f"Phase 2.5 — Destroying {len(orphans)} orphan resource(s)…")
        for nid in orphans:
            await _log(f"Destroying orphan: {nid}", "warn", nid)
            await loop.run_in_executor(
                None,
                lambda n=nid: _destroy_node_stack(
                    n, stack, stack_dir, pulumi_cmd, backend_url, pulumi_home
                ),
            )

    # ── Phase 3 ───────────────────────────────────────────────────────────────
    await _log("Phase 3 — Deploying resources…")

    deployed_outputs: dict[str, dict] = {}
    all_node_outputs: dict[str, Any]  = {}
    failed_nodes:     list[str]       = []
    total = len(order)

    for index, nid in enumerate(order, start=1):
        node  = by_id[nid]
        ntype = node.get("type", "")
        nc    = ctx.get(nid, {})
        label = node_label(nodes, nid)

        await _log(f"[{index}/{total}] ▶ {label}  ({ntype})", "info", nid)
        await _log(_SIG_WORKING, "internal", nid)

        program = build_program(
            node, ntype, nc, project, region, nodes, deployed_outputs, node_registry
        )
        if program is None:
            await _log(f"[{index}/{total}] ⚠ {label} — skipped", "warn", nid)
            failed_nodes.append(nid)
            await _log(_SIG_FAILED, "internal", nid)
            continue

        def _make_on_output(cap_nid: str) -> Callable[[str], None]:
            def on_output(line: str) -> None:
                asyncio.run_coroutine_threadsafe(
                    _log(f"  {line}", _classify_line(line), cap_nid), loop
                )
            return on_output

        try:
            outputs = await loop.run_in_executor(
                None,
                lambda p=program, n=nid: run_node_stack(
                    n, p, stack, stack_dir, project, region,
                    _make_on_output(n),
                    pulumi_cmd, backend_url, pulumi_home,
                ),
            )

            deployed_outputs[nid] = outputs
            all_node_outputs.update({f"{nid}_{k}": v for k, v in outputs.items()})

            no_change = outputs.get("__no_changes__", False)

            # ── Broadcast live props update ───────────────────────────────────
            node_inst = _get_node_instance(node, node_registry)
            if node_inst and not no_change:
                ui_props = node_inst.live_outputs(outputs, project, region)
                if ui_props and ws_manager:
                    await ws_manager.broadcast_node_props_update(nid, ui_props)
                    logger.info(
                        "orchestrator: props_update broadcast for %s → %s",
                        label, list(ui_props.keys()),
                    )

            if no_change:
                await _log(f"[{index}/{total}] ✓ {label} — no changes", "ok", nid)
                await _log(_SIG_NO_CHANGE, "internal", nid)
            else:
                await _log(f"[{index}/{total}] ✓ {label} deployed", "ok", nid)
                await _log(_SIG_DEPLOYED, "internal", nid)

        except auto.CommandError as exc:
            await _log(f"[{index}/{total}] ✗ {label} FAILED:\n{exc}", "error", nid)
            await _log(_SIG_FAILED, "internal", nid)
            failed_nodes.append(nid)
            continue

    # ── Summary ───────────────────────────────────────────────────────────────
    if failed_nodes:
        failed_labels = [node_label(nodes, n) for n in failed_nodes]
        await _log(f"Deploy finished with {len(failed_nodes)} error(s): {', '.join(failed_labels)}", "warn")
        return {"status": "partial", "failed": failed_nodes, "outputs": all_node_outputs}

    await _log(f"All {total} resources deployed ✓", "ok")
    return {"status": "ok", "failed": [], "outputs": all_node_outputs}


async def synthesize_only(
    nodes:         list[dict],
    edges:         list[dict],
    project:       str,
    region:        str = "us-central1",
    node_registry: dict | None = None,
) -> dict:
    if node_registry is None:
        from core.registry import NODE_REGISTRY
        node_registry = NODE_REGISTRY

    ctx = resolve_graph(nodes, edges, node_registry)
    try:
        order = build_dag(nodes, ctx, node_registry)
    except ValueError as exc:
        return {"error": str(exc)}

    slim = {k: {key: val for key, val in v.items() if key != "node"} for k, v in ctx.items()}
    return {
        "deployment_order": [node_label(nodes, nid) for nid in order],
        "resolved_graph":   slim,
    }