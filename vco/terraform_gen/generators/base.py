"""
terraform_gen/generators/base.py
=================================
Abstract base class for all Terraform resource generators.

Each generator knows how to convert one or more VCO node types
into valid Terraform HCL blocks. The engine calls generate() for
every node and collects the results into a structured output.

A generator returns a GeneratorResult containing:
  - resources  : list of TF resource blocks
  - variables  : list of TF variable blocks (optional, for per-resource tuning)
  - locals      : list of TF locals entries
  - outputs    : list of TF output blocks
  - data        : list of TF data source blocks
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TFBlock:
    """A single Terraform block as a dict-of-dicts, ready for HCL serialisation."""
    block_type: str           # "resource", "data", "output", "variable", "locals"
    labels: list[str]         # e.g. ["google_cloud_run_v2_service", "my_svc"]
    body: dict[str, Any]      # key → value  (nested dicts become nested blocks)
    comment: str = ""         # optional inline comment above the block


@dataclass
class GeneratorResult:
    resources: list[TFBlock] = field(default_factory=list)
    variables: list[TFBlock] = field(default_factory=list)
    locals:    list[TFBlock] = field(default_factory=list)
    data:      list[TFBlock] = field(default_factory=list)
    outputs:   list[TFBlock] = field(default_factory=list)


class BaseGenerator(ABC):
    """
    Subclass this for every VCO node type that needs Terraform output.

    handled_types — class-level set of node type strings this generator can process.
    """

    handled_types: set[str] = set()

    def can_handle(self, node_type: str) -> bool:
        return node_type in self.handled_types

    @abstractmethod
    def generate(
        self,
        node: dict,
        ctx: dict,
        project: str,
        region: str,
        all_nodes: list[dict],
        edges: list[dict],
    ) -> GeneratorResult:
        """
        Produce Terraform blocks for this node.

        node       — raw node dict from the canvas  { id, type, label, props, ... }
        ctx        — graph context built by TF engine (edge-derived relationships)
        project    — GCP project ID
        region     — default GCP region
        all_nodes  — full node list (for label / name lookups)
        edges      — full edge list
        """
        ...

    # ── Helpers shared by all generators ──────────────────────────────────────

    @staticmethod
    def resource_name(node: dict) -> str:
        """Return a valid GCP/TF resource name from node props or label."""
        import re
        props = node.get("props", {})
        label = node.get("label", node.get("id", "resource"))
        name = props.get("name") or re.sub(r"[^a-z0-9-]", "-", label.lower()).strip("-")
        # Strip trailing dashes and truncate
        return name[:50].strip("-")

    @staticmethod
    def tf_name(node: dict) -> str:
        """Return a valid Terraform identifier (underscores, no hyphens)."""
        import re
        name = BaseGenerator.resource_name(node)
        return re.sub(r"[^a-z0-9_]", "_", name).strip("_") or "resource"

    @staticmethod
    def node_by_id(all_nodes: list[dict], node_id: str) -> dict:
        for n in all_nodes:
            if n["id"] == node_id:
                return n
        return {}

    @staticmethod
    def prop(node: dict, key: str, default: Any = "") -> Any:
        return node.get("props", {}).get(key, default)
