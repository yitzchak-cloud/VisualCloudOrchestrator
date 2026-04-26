"""
api/routes/deploy.py
====================
/api/synth   — preview the deployment plan (no GCP changes)
/api/deploy  — full Pulumi deploy, streaming progress over WebSocket

Both routes are namespace-aware: the Pulumi stack directory and log
storage are scoped to payload.namespace.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.models import DeployPayload, SynthPayload
from core.log_bridge import deploy_log_for_namespace
from core.state import stack_dir as _stack_dir
from core.ws_manager import manager
from pulumi_synth import synthesize_and_deploy, synthesize_only

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["deploy"])


# ── Preview ───────────────────────────────────────────────────────────────────

@router.post("/synth")
async def synth_preview(payload: SynthPayload):
    """
    Resolve the graph and compute the deployment order **without** touching GCP.
    """
    ns = payload.namespace
    logger.info(
        "Synth preview: namespace=%s  nodes=%d  project=%s  region=%s",
        ns, len(payload.nodes), payload.project, payload.region,
    )
    result = await synthesize_only(
        nodes=payload.nodes,
        edges=payload.edges,
        project=payload.project,
        region=payload.region,
    )
    logger.info("Synth done: namespace=%s  order=%s", ns, result.get("deployment_order"))
    return result


# ── Deploy ────────────────────────────────────────────────────────────────────

@router.post("/deploy")
async def deploy(payload: DeployPayload):
    """
    Deploy all nodes to GCP via the Pulumi Automation API.
    Progress is streamed to connected WebSocket clients in real time.

    The namespace determines which Pulumi stack directory is used,
    ensuring complete isolation between canvases.
    """
    ns    = payload.namespace
    total = len(payload.nodes)
    sd    = _stack_dir(ns)

    logger.info(
        "Deploy started: namespace=%s  nodes=%d  project=%s  region=%s  stack=%s",
        ns, total, payload.project, payload.region, payload.stack,
    )

    await manager.broadcast_deploy_started(
        total=total,
        create=total,
        update=0,
        destroy=0,
        touched_ids=[n["id"] for n in payload.nodes],
    )

    # Build a namespace-bound log coroutine so events are also stored under ns
    log_fn = deploy_log_for_namespace(ns)

    result = await synthesize_and_deploy(
        nodes=payload.nodes,
        edges=payload.edges,
        project=payload.project,
        region=payload.region,
        stack=payload.stack,
        log=log_fn,
        work_dir=str(sd),
        namespace=ns,
    )

    run_status = result.get("status")

    if run_status in ("ok", "partial"):
        outputs      = result.get("outputs", {})
        failed_nodes = result.get("failed", [])
        changed      = total - len(failed_nodes)

        if outputs:
            await manager.broadcast_deploy_outputs(outputs)

        await manager.broadcast_deploy_complete(changed=changed, failed=len(failed_nodes))

        logger.info(
            "Deploy finished: namespace=%s  status=%s  changed=%d  failed=%d",
            ns, run_status, changed, len(failed_nodes),
        )
        return {"status": run_status, "outputs": outputs, "failed": failed_nodes, "namespace": ns}

    # Hard failure
    for node in payload.nodes:
        await manager.broadcast_node_status(node["id"], status="failed")
    await manager.broadcast_deploy_complete(changed=0, failed=total)

    logger.error(
        "Deploy failed: namespace=%s  phase=%s  detail=%s",
        ns, result.get("phase"), result.get("output", "")[:200],
    )
    return JSONResponse(
        status_code=500,
        content={
            "status":    "error",
            "phase":     result.get("phase"),
            "detail":    result.get("output", ""),
            "namespace": ns,
        },
    )