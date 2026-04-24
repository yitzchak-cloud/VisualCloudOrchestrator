"""
deploy/orchestrator.py
======================
Top-level async entry points consumed by the FastAPI routes:

  synthesize_and_deploy(nodes, edges, project, region, stack, log, work_dir)
      Full deploy: resolve graph → sort DAG → install plugin → deploy each node.
      Streams progress via the *log* coroutine.
      Returns {"status": "ok"|"partial"|"error", "outputs": {...}, "failed": [...]}

  synthesize_only(nodes, edges, project, region)
      Preview only — resolves the graph and returns the deployment order
      without touching GCP.
      Returns {"deployment_order": [...], "resolved_graph": {...}}

The *log* coroutine signature:
    async def log(msg: str, level: str, node_id: str | None) -> None

Sentinel messages emitted to *log*:
    "__node_working__"   — node deploy started  (level="internal")
    "__node_deployed__"  — node deploy succeeded (level="internal")
    "__node_failed__"    — node deploy failed    (level="internal")
    "__node_no_change__" — node had no changes   (level="internal")
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
from core.log_store import build_node_event, upsert_node_event

logger = logging.getLogger(__name__)

# ── Compat wrappers — handle projects where graph_resolver takes node_registry ─

def _get_node_registry() -> dict:
    try:
        from core.registry import NODE_REGISTRY
        return NODE_REGISTRY
    except Exception:
        return {}


def _resolve_graph_compat(nodes: list, edges: list) -> dict:
    import inspect
    sig = inspect.signature(resolve_graph)
    if len(sig.parameters) >= 3:
        return resolve_graph(nodes, edges, _get_node_registry())
    return resolve_graph(nodes, edges)


def _build_dag_compat(nodes: list, ctx: dict) -> list:
    import inspect
    sig = inspect.signature(build_dag)
    if len(sig.parameters) >= 3:
        return build_dag(nodes, ctx, _get_node_registry())
    return build_dag(nodes, ctx)


def _save_node_event(node_id: str, label: str, status: str, raw_log: str) -> None:
    """Persist a structured node deploy event — best-effort, never raises."""
    try:
        event = build_node_event(node_id, label, status, raw_log)
        upsert_node_event(node_id, event)
        logger.debug("node-event saved: %s → %s", node_id, status)
    except Exception as exc:
        logger.warning("_save_node_event failed: %s", exc)

# ── Sentinel constants (must match core/log_bridge.py) ────────────────────────
_SIG_WORKING   = "__node_working__"
_SIG_DEPLOYED  = "__node_deployed__"
_SIG_FAILED    = "__node_failed__"
_SIG_NO_CHANGE = "__node_no_change__"


# ─────────────────────────────────────────────────────────────────────────────
# Pulumi log line → level classifier
# ─────────────────────────────────────────────────────────────────────────────

def _classify_line(line: str) -> str:
    low = line.lower()
    if any(w in low for w in ("error", "failed", "panic")):
        return "error"
    if "warning" in low:
        return "warn"
    if any(c in line for c in ("+ ", "created", "updated")):
        return "ok"
    return "info"


# ─────────────────────────────────────────────────────────────────────────────
# Plugin installer (runs once per deploy)
# ─────────────────────────────────────────────────────────────────────────────

def _install_gcp_plugin(stack_dir: Path) -> tuple[Any, str, str]:
    """
    Download Pulumi CLI (if not cached), login to local file backend,
    and install the GCP provider plugin.

    Returns: (pulumi_command, backend_url, pulumi_home)
    """
    cmd        = get_pulumi_command(stack_dir)
    state_dir  = (stack_dir / ".pulumi-state").resolve()
    b_url      = os.environ.get("PULUMI_BACKEND_URL", "file://" + state_dir.as_posix())
    p_home     = str((stack_dir / ".pulumi-home").resolve())

    state_dir.mkdir(parents=True, exist_ok=True)
    (stack_dir / ".pulumi-home").mkdir(parents=True, exist_ok=True)

    shared_env = {
        "PULUMI_BACKEND_URL":       b_url,
        "PULUMI_CONFIG_PASSPHRASE": os.environ.get("PULUMI_CONFIG_PASSPHRASE", ""),
        "PULUMI_SKIP_UPDATE_CHECK": "1",
        "PULUMI_ACCESS_TOKEN":      "",
        "PULUMI_HOME":              p_home,
    }

    logger.info("Logging in to Pulumi backend: %s", b_url)
    cmd.run(["login", b_url], cwd=str(stack_dir), additional_env=shared_env)

    ws = auto.LocalWorkspace(
        work_dir=str(stack_dir),
        pulumi_home=p_home,
        env_vars=shared_env,
        pulumi_command=cmd,
    )
    logger.info("Installing Pulumi GCP plugin v7 …")
    ws.install_plugin("gcp", "v7")
    logger.info("GCP plugin ready")
    return cmd, b_url, p_home


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_and_deploy(
    nodes:    list[dict],
    edges:    list[dict],
    project:  str,
    region:   str = "us-central1",
    stack:    str = "dev",
    log:      Callable[[str, str, str | None], Any] | None = None,
    work_dir: str | None = None,
) -> dict:
    """
    Orchestrate a full deploy run:
      Phase 1 — resolve graph + topological sort
      Phase 2 — install GCP plugin (once)
      Phase 2.5 — destroy orphan resources (nodes removed from diagram)
      Phase 3 — deploy each node in order, streaming progress via *log*
    """

    async def _log(msg: str, level: str = "info", node_id: str | None = None) -> None:
        if log:
            await log(msg, level, node_id)

    stack_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="vco_pulumi_"))
    stack_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    # ── Phase 1: resolve + sort ───────────────────────────────────────────────
    await _log("Phase 1 — Analysing graph dependencies…")
    logger.info("orchestrator: resolve_graph  nodes=%d  edges=%d", len(nodes), len(edges))
    ctx = _resolve_graph_compat(nodes, edges)

    try:
        order = _build_dag_compat(nodes, ctx)
    except ValueError as exc:
        logger.error("orchestrator: DAG cycle — %s", exc)
        await _log(str(exc), "error")
        return {"status": "error", "phase": "dag", "output": str(exc)}

    by_id = {n["id"]: n for n in nodes}
    order_labels = " → ".join(node_label(nodes, nid) for nid in order)
    await _log(f"Deployment order ({len(order)} nodes): {order_labels}")
    logger.info("orchestrator: deployment order → %s", order)

    # ── Phase 2: install plugin ───────────────────────────────────────────────
    await _log("Phase 2 — Installing Pulumi GCP plugin…")
    try:
        pulumi_cmd, backend_url, pulumi_home = await loop.run_in_executor(
            None, _install_gcp_plugin, stack_dir
        )
    except Exception as exc:
        logger.error("orchestrator: plugin install failed — %s", exc)
        await _log(f"Plugin install failed: {exc}", "error")
        return {"status": "error", "phase": "plugin", "output": str(exc)}

    # ── Phase 2.5: destroy orphans ────────────────────────────────────────────
    # pulumi_cmd / backend_url / pulumi_home are guaranteed to exist here
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

    # ── Phase 3: deploy node by node ─────────────────────────────────────────
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
        logger.info("orchestrator: [%d/%d] deploying %s (%s)", index, total, label, ntype)
        await _log(_SIG_WORKING, "internal", nid)

        # Build the Pulumi program for this node type
        program = build_program(node, ntype, nc, project, region, nodes, deployed_outputs, _get_node_registry())
        if program is None:
            await _log(f"[{index}/{total}] ⚠ {label} — skipped (missing dependency or unknown type)", "warn", nid)
            failed_nodes.append(nid)
            await _log(_SIG_FAILED, "internal", nid)
            _save_node_event(nid, label, "skipped", "Skipped — missing dependency or unknown type")
            continue

        # Per-node buffer — silently collects every Pulumi output line
        # We do NOT stream individual lines to the UI — one summary entry is sent after completion
        node_log_buffer: list[str] = []

        def _make_on_output(cap_buf: list) -> Callable[[str], None]:
            def on_output(line: str) -> None:
                cap_buf.append(line)   # collect only — no WS broadcast per line
            return on_output

        try:
            outputs = await loop.run_in_executor(
                None,
                lambda p=program, n=nid, buf=node_log_buffer: run_node_stack(
                    n, p, stack, stack_dir, project, region,
                    _make_on_output(buf),
                    pulumi_cmd, backend_url, pulumi_home,
                ),
            )

            deployed_outputs[nid] = outputs
            all_node_outputs.update({f"{nid}_{k}": v for k, v in outputs.items()})
            raw_log = "\n".join(node_log_buffer)

            if outputs.get("__no_changes__"):
                # Single summary log entry
                await _log(f"[{index}/{total}] ✓ {label} — no changes", "ok", nid)
                await _log(_SIG_NO_CHANGE, "internal", nid)
                _save_node_event(nid, label, "no_change", raw_log)
            else:
                # Single summary log entry — details available in node event card
                out_keys = [k for k in outputs if not k.startswith("__")]
                out_str  = "  ".join(f"{k}={outputs[k]}" for k in out_keys[:3])
                await _log(f"[{index}/{total}] ✓ {label} deployed  {out_str}", "ok", nid)
                await _log(_SIG_DEPLOYED, "internal", nid)
                _save_node_event(nid, label, "deployed", raw_log)

            logger.info("orchestrator: %s done  outputs=%s", label, list(outputs.keys()))

        except auto.CommandError as exc:
            raw_log = "\n".join(node_log_buffer) + "\n" + str(exc)
            # Build clean one-line error summary for the log panel
            from core.log_store import build_node_event as _bne
            ev = _bne(nid, label, "failed", raw_log)
            clean_err = ev.get("summary", str(exc)[:120])
            await _log(f"[{index}/{total}] ✗ {label} — {clean_err}", "error", nid)
            await _log(_SIG_FAILED, "internal", nid)
            _save_node_event(nid, label, "failed", raw_log)
            failed_nodes.append(nid)
            logger.error("orchestrator: %s FAILED — %s", label, str(exc)[:300])
            continue   # keep deploying remaining nodes

    # ── Summary ───────────────────────────────────────────────────────────────
    if failed_nodes:
        failed_labels = [node_label(nodes, n) for n in failed_nodes]
        msg = f"Deploy finished with {len(failed_nodes)} error(s): {', '.join(failed_labels)}"
        await _log(msg, "warn")
        logger.warning("orchestrator: %s", msg)
        return {"status": "partial", "failed": failed_nodes, "outputs": all_node_outputs}

    await _log(f"All {total} resources deployed ✓", "ok")
    logger.info("orchestrator: all %d resources deployed successfully", total)
    return {"status": "ok", "failed": [], "outputs": all_node_outputs}


# ─────────────────────────────────────────────────────────────────────────────
# Preview only
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_only(
    nodes:   list[dict],
    edges:   list[dict],
    project: str,
    region:  str = "us-central1",
) -> dict:
    """
    Resolve the graph and return the deployment plan without touching GCP.
    """
    logger.info("synthesize_only: %d nodes", len(nodes))
    ctx = _resolve_graph_compat(nodes, edges)

    try:
        order = _build_dag_compat(nodes, ctx)
    except ValueError as exc:
        logger.error("synthesize_only: DAG cycle — %s", exc)
        return {"error": str(exc)}

    slim = {
        k: {key: val for key, val in v.items() if key != "node"}
        for k, v in ctx.items()
    }
    result = {
        "deployment_order": [node_label(nodes, nid) for nid in order],
        "resolved_graph":   slim,
    }
    logger.info("synthesize_only: order=%s", result["deployment_order"])
    return result