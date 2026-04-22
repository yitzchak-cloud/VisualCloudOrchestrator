"""
nodes/base_node.py
==================
Base class for all GCP resource nodes.

Every node is self-describing — adding a new resource requires ONE file only.

Each GCPNode subclass declares:

  ClassVar (UI / registry):
    inputs, outputs, node_color, icon, category, description,
    params_schema, url_field

  Deploy methods:
    resolve_edges(src_id, tgt_id, src_type, tgt_type, ctx) → bool
    dag_deps(ctx)                                           → list[node_id]
    pulumi_program(ctx, project, region, all_nodes, deployed_outputs)
                                                            → Callable | None

  Post-deploy sync methods:
    live_outputs(pulumi_outputs, project, region)  → dict
        Maps Pulumi exports → UI props to write back onto the canvas node.
        Called after every successful deploy; result is broadcast via WS.

    log_source(pulumi_outputs, project, region)    → LogSource | None
        Returns a Cloud Logging query descriptor for the SSE log stream,
        or None if this resource type has no meaningful log stream.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, ClassVar

from nodes.port_types import PortType, PORT_META


# ── Port descriptor ───────────────────────────────────────────────────────────

@dataclass
class Port:
    name:      str
    port_type: PortType
    multi:     bool = False
    required:  bool = False
    multi_in:  bool = False


# ── Log source descriptor ─────────────────────────────────────────────────────

@dataclass
class LogSource:
    """
    Describes how to query Cloud Logging for a GCP resource.

    filter    — Cloud Logging filter string, e.g.:
                  'resource.type="cloud_run_revision"
                   AND resource.labels.service_name="my-svc"'
    project   — GCP project id (filled by engine from deploy config)
    page_size — max entries per poll
    order     — "desc" (newest first) or "asc"
    """
    filter:    str
    project:   str = ""
    page_size: int = 50
    order:     str = "desc"


# ── Base node ─────────────────────────────────────────────────────────────────

@dataclass
class GCPNode:
    node_id: str
    label:   str

    inputs:        ClassVar[list[Port]]  = []
    outputs:       ClassVar[list[Port]]  = []
    node_color:    ClassVar[str]         = "#1e293b"
    icon:          ClassVar[str]         = "box"
    category:      ClassVar[str]         = "General"
    description:   ClassVar[str]        = ""
    params_schema: ClassVar[list[dict]] = []
    url_field:     ClassVar[str | None] = None

    # ── UI schema ─────────────────────────────────────────────────────────────

    @classmethod
    def ui_schema(cls) -> dict:
        return {
            "type":          cls.__name__,
            "label":         cls.__name__.replace("Node", "").replace("_", " "),
            "description":   cls.description,
            "color":         cls.node_color,
            "icon":          cls.icon,
            "category":      cls.category,
            "params_schema": cls.params_schema,
            "url_field":     cls.url_field,
            "inputs": [
                {
                    "name":     p.name,
                    "type":     p.port_type.value,
                    "multi":    p.multi,
                    "multi_in": p.multi_in,
                    "required": p.required,
                    "color":    PORT_META[p.port_type.value]["color"],
                    "label":    PORT_META[p.port_type.value]["label"],
                }
                for p in cls.inputs
            ],
            "outputs": [
                {
                    "name":  p.name,
                    "type":  p.port_type.value,
                    "multi": p.multi,
                    "color": PORT_META[p.port_type.value]["color"],
                    "label": PORT_META[p.port_type.value]["label"],
                }
                for p in cls.outputs
            ],
        }

    def to_yaml_dict(self) -> dict:
        return {
            "type":          self.__class__.__name__,
            "node_id":       self.node_id,
            "label":         self.label,
            "category":      self.__class__.category,
            "params_schema": self.__class__.params_schema,
        }

    # ── Deploy logic (subclasses override) ────────────────────────────────────

    def resolve_edges(
        self,
        src_id:   str,
        tgt_id:   str,
        src_type: str,
        tgt_type: str,
        ctx:      dict[str, Any],
    ) -> bool:
        """Claim and process one edge. Return True if handled."""
        return False

    def dag_deps(self, ctx: dict[str, Any]) -> list[str]:
        """Return node IDs that must be deployed before this node."""
        return []

    def pulumi_program(
        self,
        ctx:              dict[str, Any],
        project:          str,
        region:           str,
        all_nodes:        list[dict],
        deployed_outputs: dict[str, dict],
    ) -> Callable[[], None] | None:
        """Return Pulumi program closure, or None to skip."""
        return None

    # ── Post-deploy sync (subclasses override) ────────────────────────────────

    def live_outputs(
        self,
        pulumi_outputs: dict[str, Any],
        project:        str,
        region:         str,
    ) -> dict[str, Any]:
        """
        Map Pulumi exports → UI props to write back onto the canvas node.

        Called after every successful deploy. The returned dict is sent via
        WebSocket as a  node_props_update  event so the UI can update fields
        like service_url, resource name, etc. without a manual refresh.

        Default: pass-through (returns pulumi_outputs as-is).

        Override example (Cloud Run):
            return {"service_url": pulumi_outputs.get("uri", "")}
        """
        return dict(pulumi_outputs)

    def log_source(
        self,
        pulumi_outputs: dict[str, Any],
        project:        str,
        region:         str,
    ) -> "LogSource | None":
        """
        Return a LogSource for the SSE /api/logs/{node_id} stream.

        The SSE endpoint calls this to discover what Cloud Logging filter
        to use when tailing logs for this specific resource.

        *pulumi_outputs* — whatever pulumi_program() exported (uri, name, id…)

        Return None for resources with no meaningful log stream (VPC, SA, …).

        Default: None.
        """
        return None