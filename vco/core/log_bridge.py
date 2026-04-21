"""
core/log_bridge.py
==================
Translates raw internal signals emitted by the deploy engine into typed
WebSocket events (via ws_manager).

The deploy engine calls a simple  log(msg, level, node_id)  coroutine.
This module provides that coroutine and handles the two special sentinel
messages (__node_working__, __node_deployed__, __node_failed__) so the
engine itself stays free of WebSocket knowledge.
"""
from __future__ import annotations

import logging
from typing import Any

from core.ws_manager import manager

logger = logging.getLogger(__name__)

# Sentinel strings emitted by pulumi_synth.deploy_dag
_SENTINEL_WORKING  = "__node_working__"
_SENTINEL_DEPLOYED = "__node_deployed__"
_SENTINEL_FAILED   = "__node_failed__"
_SENTINEL_NO_CHANGE = "__node_no_change__"


async def deploy_log(msg: str, level: str = "info", node_id: str | None = None) -> None:
    """
    Drop-in log coroutine to pass into synthesize_and_deploy().

    • Sentinel messages → typed WS events  (no visible log line)
    • Everything else   → broadcast_log
    """
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
