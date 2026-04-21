"""
api/routes/realtime.py
======================
/api/logs/{node_id}  — SSE heartbeat stream per node
/ws                  — WebSocket endpoint (connect once, receive all events)
"""
from __future__ import annotations

import asyncio
import datetime
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from core.ws_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])


@router.get("/api/logs/{node_id}")
async def stream_logs(node_id: str):
    """
    Server-Sent Events heartbeat for a specific node.
    Useful for long-running operations where the client wants a simple
    HTTP stream instead of a full WebSocket connection.
    """
    logger.debug("SSE log stream opened for node %s", node_id)

    async def generate():
        while True:
            ts = datetime.datetime.utcnow().isoformat()
            yield f"data: [INFO] {node_id}: heartbeat at {ts}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Primary real-time channel.
    Clients connect here to receive all deploy / graph events.
    Messages from the client are silently ignored (pub-sub, not chat).
    """
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep connection alive; we don't act on client messages
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as exc:
        logger.warning("Unexpected WS error: %s", exc)
        manager.disconnect(ws)
