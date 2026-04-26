"""
api/models.py
=============
Pydantic request / response models for all VCO API routes.

All payload models now include an optional *namespace* field (default "default").
Routes pass this field down to core helpers so every piece of data
(graph YAML, Pulumi stacks, logs, node events) is fully isolated per namespace.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, Field


class GraphPayload(BaseModel):
    """Save the current canvas state (nodes + edges)."""
    nodes:     list[dict] = Field(..., description="List of node objects from the canvas")
    edges:     list[dict] = Field(..., description="List of edge objects from the canvas")
    namespace: str        = Field(default="default", description="Namespace for this graph")


class SynthPayload(BaseModel):
    """Preview what *would* be deployed without touching GCP."""
    nodes:     list[dict]
    edges:     list[dict]
    namespace: str = Field(default="default")
    project:   str = Field(
        default_factory=lambda: os.getenv("DEFAULT_GCP_PROJECT", "hrz-geo-dig-res-endor-1")
    )
    region: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_GCP_REGION", "me-west1")
    )


class DeployPayload(BaseModel):
    """Full deploy: synthesise + run Pulumi up."""
    nodes:     list[dict]
    edges:     list[dict]
    namespace: str = Field(default="default")
    project:   str = Field(
        default_factory=lambda: os.getenv("DEFAULT_GCP_PROJECT", "hrz-geo-dig-res-endor-1")
    )
    region: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_GCP_REGION", "me-west1")
    )
    stack: str = Field(default="dev", description="Pulumi stack name (e.g. dev / staging / prod)")


class EdgeValidation(BaseModel):
    """Quick validation check before the UI draws an edge."""
    source_type: str
    target_type: str