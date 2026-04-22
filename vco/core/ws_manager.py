"""
core/ws_manager.py
==================
WebSocket connection pool + typed broadcast helpers.

All UI events are sent through typed helpers (broadcast_log, broadcast_node_status …)
so the shape of every message is defined in exactly one place.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)
        logger.info("WS client connected  (total=%d)", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.remove(ws)
        logger.info("WS client disconnected  (total=%d)", len(self._active))

    # ── low-level broadcast ──────────────────────────────────────────────────

    async def broadcast(self, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            logger.warning("Dropping dead WS connection")
            self._active.remove(ws)

    # ── typed event helpers ──────────────────────────────────────────────────
    # Every key in these dicts is intentional – the UI knows exactly what
    # fields to expect for each event type.

    async def broadcast_log(
        self,
        msg: str,
        level: str = "info",
        node_id: str | None = None,
    ) -> None:
        """
        General log line (shown in the deploy log panel).

        Payload:
            event   : "log"
            msg     : human-readable message
            level   : "info" | "ok" | "warn" | "error"
            node_id : optional – routes the line to a specific node panel
        """
        payload: dict[str, Any] = {"event": "log", "msg": msg, "level": level}
        if node_id:
            payload["node_id"] = node_id
        logger.debug("[log/%s] %s", level, msg)
        await self.broadcast(payload)

    async def broadcast_node_working(self, node_id: str) -> None:
        """
        Marks a node as 'in progress' in the UI (spinner / orange badge).

        Payload:
            event   : "node_working"
            node_id : the node being deployed right now
        """
        logger.debug("[node_working] %s", node_id)
        await self.broadcast({"event": "node_working", "node_id": node_id})

    async def broadcast_node_status(
        self,
        node_id: str,
        status: str,                       # "deployed" | "failed" | "no_change"
        action: str | None = None,         # "create" | "update" | None
    ) -> None:
        """
        Updates the status badge / colour of a node card in the UI.

        Payload:
            event   : "node_status"
            node_id : target node
            status  : "deployed" | "failed" | "no_change"
            action  : "create" | "update"  (optional)
        """
        payload: dict[str, Any] = {"event": "node_status", "node_id": node_id, "status": status}
        if action:
            payload["action"] = action
        logger.info("[node_status] %s → %s (%s)", node_id, status, action or "—")
        await self.broadcast(payload)

    async def broadcast_deploy_started(
        self,
        total: int,
        create: int,
        update: int,
        destroy: int,
        touched_ids: list[str],
    ) -> None:
        """
        Fired once when a deploy run begins.

        Payload:
            event       : "deploy_started"
            total       : total nodes to process
            create      : nodes to create
            update      : nodes to update
            destroy     : nodes to destroy
            touched_ids : list of node IDs that will be touched
        """
        logger.info(
            "[deploy_started] total=%d  create=%d  update=%d  destroy=%d",
            total, create, update, destroy,
        )
        await self.broadcast({
            "event":       "deploy_started",
            "total":       total,
            "create":      create,
            "update":      update,
            "destroy":     destroy,
            "touched_ids": touched_ids,
        })

    async def broadcast_deploy_outputs(self, outputs: dict[str, Any]) -> None:
        """
        Fired after a successful deploy to propagate live resource URLs / IDs.

        Payload:
            event   : "deploy_outputs"
            outputs : flat dict  (e.g. {"CloudRunNode-123_uri": "https://…"})
        """
        logger.info("[deploy_outputs] keys=%s", list(outputs.keys()))
        await self.broadcast({"event": "deploy_outputs", "outputs": outputs})

    async def broadcast_deploy_complete(self, changed: int, failed: int = 0) -> None:
        """
        Fired when the deploy run finishes (success or partial).

        Payload:
            event   : "deploy_complete"
            changed : number of successfully changed nodes
            failed  : number of failed nodes
        """
        logger.info("[deploy_complete] changed=%d  failed=%d", changed, failed)
        await self.broadcast({"event": "deploy_complete", "changed": changed, "failed": failed})

    async def broadcast_graph_saved(self, node_count: int) -> None:
        """
        Payload:
            event      : "graph_saved"
            node_count : total nodes in the saved graph
        """
        await self.broadcast({"event": "graph_saved", "node_count": node_count})
    
    async def broadcast_graph_saved(self, node_count: int) -> None:
        """
        Payload:
            event      : "graph_saved"
            node_count : total nodes in the saved graph
        """
        await self.broadcast({"event": "graph_saved", "node_count": node_count})

    # ── התוספת החדשה שעלייך להדביק כאן: ──────────────────────────────────────

    async def broadcast_node_props_update(self, node_id: str, props: dict) -> None:
        """
        Notify all connected clients that a node's props have been updated
        with live values from a freshly completed deploy.

        Frontend should merge *props* into the matching node's data.props.
        """
        await self.broadcast({
            "type":    "node_props_update",
            "node_id": node_id,
            "props":   props,
        })

# Singleton — import and use from anywhere
manager = ConnectionManager()
