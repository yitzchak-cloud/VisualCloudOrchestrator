"""
api/routes/nodes.py
===================
/api/node-types   — list all registered GCP node types for the palette
/api/validate-edge — quick edge compatibility check
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.models import EdgeValidation, NodeSchemaRequest
from core.registry import NODE_REGISTRY
from nodes.port_types import PORT_META

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["nodes"])


@router.get("/node-types")
def get_node_types():
    """Return the UI schema for every registered node type."""
    schemas = []
    errors = []

    for cls in NODE_REGISTRY.values():
        try:
            schemas.append(cls.ui_schema())
        except Exception as e:
            errors.append((cls.__name__, str(e)))

    logger.error(errors)
    logger.debug("Returning %d node-type schemas", len(schemas))
    return schemas


@router.post("/validate-edge")
def validate_edge(body: EdgeValidation):
    """
    Check whether an edge between two node types is valid.

    Returns:
        valid  : bool
        reason : str | null   (null when valid)
    """
    # TODO: extend with a proper compatibility matrix per node type.
    valid = body.source_type == body.target_type
    reason = None if valid else f"Cannot connect {body.source_type} → {body.target_type}"
    logger.debug("validate-edge %s → %s : valid=%s", body.source_type, body.target_type, valid)
    return {"valid": valid, "reason": reason}


@router.post("/node-schema")
def get_node_schema(body: NodeSchemaRequest):
    """
    Return the live schema for a specific node instance,
    given its type + current props. Used when a param with
    triggers_refresh=true changes.
    """
    cls = NODE_REGISTRY.get(body.node_type)
    if not cls:
        raise HTTPException(status_code=404, detail=f"Unknown type: {body.node_type}")

    # Instantiate with a dummy id so get_inputs / get_outputs work
    instance = cls(node_id="__preview__", label="__preview__")
    instance._props = body.props

    schema = cls.ui_schema()

    # Override ports if the node implements dynamic port methods
    if hasattr(instance, "get_inputs"):
        schema["inputs"] = [
            {
                "name":     p.name,
                "type":     p.port_type.value,
                "multi":    p.multi,
                "multi_in": p.multi_in,
                "required": p.required,
                "color":    PORT_META[p.port_type.value]["color"],
                "label":    PORT_META[p.port_type.value]["label"],
            }
            for p in instance.get_inputs()
        ]
    if hasattr(instance, "get_outputs"):
        schema["outputs"] = [
            {
                "name":  p.name,
                "type":  p.port_type.value,
                "multi": p.multi,
                "color": PORT_META[p.port_type.value]["color"],
                "label": PORT_META[p.port_type.value]["label"],
            }
            for p in instance.get_outputs()
        ]

    return schema