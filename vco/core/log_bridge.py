"""
core/log_bridge.py
==================
Translates raw internal signals from the deploy engine into typed
WebSocket events (via ws_manager).

New: deploy_log_for_namespace(namespace) returns a coroutine that
is bound to a specific namespace so log lines are also persisted under
the correct namespace directory.

The original module-level deploy_log coroutine is kept for backwards
compatibility (routes/deploy.py previously imported it directly).
"""
from __future__ import annotations

import logging
from typing import Any

from core.ws_manager import manager

logger = logging.getLogger(__name__)

# Sentinel strings emitted by pulumi_synth.deploy_dag
_SENTINEL_WORKING   = "__node_working__"
_SENTINEL_DEPLOYED  = "__node_deployed__"
_SENTINEL_FAILED    = "__node_failed__"
_SENTINEL_NO_CHANGE = "__node_no_change__"


def deploy_log_for_namespace(namespace: str = "default"):
    """
    Return a log coroutine bound to *namespace*.

    The returned coroutine has the signature expected by synthesize_and_deploy:
        async def log(msg, level, node_id) -> None

    Sentinel messages are converted to typed WS events.
    Regular messages are broadcast and optionally stored (the orchestrator
    already calls append_log via log_store for final outcome lines;
    we don't double-append here).
    """

    async def _log(msg: str, level: str = "info", node_id: str | None = None) -> None:
        if msg == _SENTINEL_WORKING and node_id:
            await manager.broadcast_node_working(node_id)
            return
        if msg == _SENTINEL_DEPLOYED and node_id:
            await manager.broadcast_node_status(node_id, status="deployed", action="create")
            return
        if msg == _SENTINEL_FAILED and node_id:
            await manager.broadcast_node_status(node_id, status="failed")
            return
        if msg == _SENTINEL_NO_CHANGE and node_id:
            await manager.broadcast_node_status(node_id, status="no_change")
            return

        # Regular log line
        await manager.broadcast_log(msg, level, node_id)

    return _log


# ── Legacy coroutine (default namespace) ──────────────────────────────────────
# Kept so code that does  `from core.log_bridge import deploy_log`  still works.

async def deploy_log(msg: str, level: str = "info", node_id: str | None = None) -> None:
    fn = deploy_log_for_namespace("default")
    await fn(msg, level, node_id)