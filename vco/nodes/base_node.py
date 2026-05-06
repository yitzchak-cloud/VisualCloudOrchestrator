"""
nodes/base_node.py
==================
Base class for all GCP resource nodes.

Terraform dataclasses
---------------------
  TFBlock   — a single HCL block (resource / data / output / variable)
  TFResult  — legacy flat-file result (kept for compatibility, not used by engine)
  TFModule  — describes one Terraform module directory for a single node

  Each GCPNode subclass implements:
    terraform_module(ctx, project, region, all_nodes) → TFModule | None

  TFModule fields
  ---------------
    module_name  str                 — Terraform identifier, e.g. "my_sa"
                                       used as: module.<module_name>
    resources    list[TFBlock]       — goes into modules/<name>/main.tf
    data         list[TFBlock]       — data sources, also main.tf
    variables    list[TFBlock]       — modules/<name>/variables.tf
    outputs      list[TFBlock]       — modules/<name>/outputs.tf
    call_vars    dict[str, str]      — key = HCL expression pairs injected
                                       into the root module{} call block.
                                       Values are raw HCL (not quoted):
                                         "sa_email" → "module.other_sa.email"
                                         "image"    → '"gcr.io/project/img"'
                                       Use _hcl_str(val) for quoted strings.

Cross-module references
-----------------------
Pass a reference to another module's output via call_vars:
    "sa_email": f"module.{sa_tf_id}.email"
Terraform resolves the implicit dependency automatically — no explicit
depends_on needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import re
from typing import Any, Callable, ClassVar
from pathlib import Path as LocalPath
import yaml

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
    filter:    str
    project:   str = ""
    page_size: int = 50
    order:     str = "desc"


# ── Terraform dataclasses ─────────────────────────────────────────────────────

@dataclass
class TFBlock:
    """A single Terraform block (resource / data / output / variable / locals)."""
    block_type: str
    labels:     list[str]
    body:       dict[str, Any]
    comment:    str = ""


@dataclass
class TFResult:
    """Legacy flat-file result — kept for any code that still uses it."""
    resources: list[TFBlock] = field(default_factory=list)
    data:      list[TFBlock] = field(default_factory=list)
    outputs:   list[TFBlock] = field(default_factory=list)
    variables: list[TFBlock] = field(default_factory=list)


@dataclass
class TFModule:
    """
    Describes one Terraform module directory for a single GCP node.

    module_name  — used as the Terraform identifier: module.<module_name>
                   and as the directory name: modules/<module_name>/
                   Must be a valid Terraform identifier (letters, digits, _).

    resources    — resource + IAM blocks → modules/<name>/main.tf
    data         — data source blocks   → modules/<name>/main.tf (above resources)
    variables    — input variable blocks → modules/<name>/variables.tf
                   Always include at minimum:
                     variable "project_id" { type = string }
                     variable "region"     { type = string }
    outputs      — output blocks         → modules/<name>/outputs.tf
                   Each output becomes accessible as module.<name>.<output_name>

    call_vars    — dict of variable_name → HCL expression injected into the
                   root module{} call block.
                   Raw HCL — use _hcl_str() for string literals:
                     "sa_email": "module.other_sa.email"         ← reference
                     "image":    _hcl_str("gcr.io/project/img")  ← literal
    """
    module_name: str
    resources:   list[TFBlock]      = field(default_factory=list)
    data:        list[TFBlock]      = field(default_factory=list)
    variables:   list[TFBlock]      = field(default_factory=list)
    outputs:     list[TFBlock]      = field(default_factory=list)
    call_vars:   dict[str, str]     = field(default_factory=dict)


# ── HCL helpers ───────────────────────────────────────────────────────────────

def _hcl_str(value: str) -> str:
    """Wrap a Python string as a quoted HCL string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _hcl_var(name: str) -> str:
    """Reference a root-level Terraform variable: var.<name>"""
    return f"var.{name}"


def _module_ref(module_name: str, output_name: str) -> str:
    """Reference a module output: module.<name>.<output>"""
    return f"module.{module_name}.{output_name}"


# ── Standard module variables (every module needs these) ──────────────────────

def _std_module_variables() -> list[TFBlock]:
    """Return the standard project_id + region variables every module needs."""
    return [
        TFBlock(
            block_type="variable", labels=["project_id"],
            body={"description": "GCP project ID", "type": "string"},
        ),
        TFBlock(
            block_type="variable", labels=["region"],
            body={"description": "GCP region", "type": "string"},
        ),
    ]


# ── Shared name helpers ────────────────────────────────────────────────────────

def _resource_name(node_dict: dict) -> str:
    props = node_dict.get("props", {})
    label = node_dict.get("label", node_dict.get("id", "resource"))
    return props.get("name") or re.sub(r"[^a-z0-9-]", "-", label.lower()).strip("-")

def _tf_name(node_dict: dict) -> str:
    """Valid Terraform identifier (underscores, no hyphens, max 60 chars)."""
    name = _resource_name(node_dict)
    ident = re.sub(r"[^a-z0-9_]", "_", name).strip("_") or "resource"
    return ident[:60]

def _node_label(all_nodes: list[dict], node_id: str) -> str:
    for n in all_nodes:
        if n["id"] == node_id:
            return n.get("label", node_id)
    return node_id

def _node_name(all_nodes: list[dict], node_id: str) -> str:
    for n in all_nodes:
        if n["id"] == node_id:
            return _resource_name(n)
    return node_id

def _node_by_id(all_nodes: list[dict], node_id: str) -> dict:
    for n in all_nodes:
        if n["id"] == node_id:
            return n
    return {}


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
    description:   ClassVar[str]         = ""
    params_schema: ClassVar[list[dict]]  = []
    url_field:     ClassVar[str | None]  = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        try:
            module = importlib.import_module(cls.__module__)
            if hasattr(module, "__file__") and module.__file__:
                class_dir = LocalPath(module.__file__).parent
                yaml_files = list(class_dir.glob("*_params.yaml"))
                if yaml_files:
                    with open(yaml_files[0], "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                        if isinstance(data, list):
                            cls.params_schema = data
        except Exception:
            pass

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

    # ── Deploy (Pulumi) ────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        return False

    def dag_deps(self, ctx: dict[str, Any]) -> list[str]:
        return []

    def pulumi_program(
        self, ctx, project, region, all_nodes, deployed_outputs
    ) -> Callable[[], None] | None:
        return None

    # ── Terraform ─────────────────────────────────────────────────────────────

    def terraform_module(
        self,
        ctx:       dict[str, Any],
        project:   str,
        region:    str,
        all_nodes: list[dict],
    ) -> TFModule | None:
        """
        Return a TFModule describing this node's Terraform module directory.

        The engine places the result under  modules/<module_name>/  and adds
        a module{} call block to the root main.tf.

        Cross-resource references go through call_vars:
            sa_id = ctx.get("service_account_id", "")
            if sa_id:
                sa_tf = _tf_name(_node_by_id(all_nodes, sa_id))
                module.call_vars["sa_email"] = f"module.{sa_tf}.email"

        Return None to skip Terraform generation (visual/UI-only nodes).

        Default: None.
        """
        return None

    # ── Post-deploy ────────────────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict[str, Any]:
        return dict(pulumi_outputs)

    def log_source(self, pulumi_outputs, project, region) -> "LogSource | None":
        return None