"""
api/routes/namespaces.py
========================
CRUD routes for namespace management.

  GET    /api/namespaces           — list all namespaces
  POST   /api/namespaces           — create a new namespace
  DELETE /api/namespaces/{name}    — delete a namespace and ALL its data
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.state import create_namespace, delete_namespace, list_namespaces, validate_namespace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/namespaces", tags=["namespaces"])


class NamespaceCreate(BaseModel):
    name: str


@router.get("")
def get_namespaces():
    """Return all existing namespace names."""
    names = list_namespaces()
    logger.debug("list_namespaces → %s", names)
    return {"namespaces": names}


@router.post("")
def post_namespace(body: NamespaceCreate):
    """Create a new namespace. 400 if name is invalid or already exists."""
    name = body.name.strip()
    if not validate_namespace(name):
        raise HTTPException(
            status_code=400,
            detail="Invalid namespace name. Use only letters, digits, hyphens or underscores (max 64 chars).",
        )
    ok = create_namespace(name)
    if not ok:
        raise HTTPException(status_code=409, detail=f"Namespace '{name}' already exists.")
    logger.info("Namespace created: %s", name)
    return {"created": name}


@router.delete("/{name}")
def del_namespace(name: str):
    """Delete a namespace and ALL its data. 'default' cannot be deleted."""
    ok = delete_namespace(name)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete namespace '{name}' (not found or protected).",
        )
    logger.info("Namespace deleted: %s", name)
    return {"deleted": name}