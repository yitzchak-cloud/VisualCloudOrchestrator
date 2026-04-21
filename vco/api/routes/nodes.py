"""
api/routes/nodes.py
===================
/api/node-types   — list all registered GCP node types for the palette
/api/validate-edge — quick edge compatibility check
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from api.models import EdgeValidation
from core.registry import NODE_REGISTRY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["nodes"])


@router.get("/node-types")
def get_node_types():
    """Return the UI schema for every registered node type."""
    schemas = [cls.ui_schema() for cls in NODE_REGISTRY.values()]
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
