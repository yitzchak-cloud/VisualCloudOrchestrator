"""
terraform_gen/engine.py
========================
Terraform workspace generator — module-per-resource architecture.

Structure
---------
Every GCP resource becomes its own Terraform module under modules/:

    terraform/
      main.tf              ← module calls only (one per node)
      variables.tf         ← project_id, region, environment
      terraform.tfvars     ← default values
      outputs.tf           ← re-exports from modules
      modules/
        <node_tf_id>/
          main.tf          ← resource + IAM blocks for this node
          variables.tf     ← all inputs this module needs
          outputs.tf       ← what this node exports to callers

Why modules?
------------
- No name collisions: two SA nodes produce two separate modules with
  completely isolated Terraform namespaces.
- Cross-resource references: SA email is passed as
    module.my_sa.email  → variable in CR module
  Terraform resolves the implicit ordering automatically.
- Industry standard: mirrors how real teams organise GCP Terraform.

How it works
------------
1. resolve_graph() builds ctx (same as Pulumi — single source of truth).
2. For each node, node.terraform_module() returns a TFModule describing
   the files for that node's module directory.
3. engine assembles:
     modules/<tf_id>/main.tf      from TFModule.resources + TFModule.data
     modules/<tf_id>/variables.tf from TFModule.variables
     modules/<tf_id>/outputs.tf   from TFModule.outputs
     main.tf                      one module{} call per node
     variables.tf                 standard root variables
     terraform.tfvars             filled defaults
     outputs.tf                   one output per module output

Node interface
--------------
Each GCPNode subclass implements:

    def terraform_module(self, ctx, project, region, all_nodes) -> TFModule | None

TFModule is defined in nodes/base_node.py alongside TFBlock/TFResult.
Return None to skip Terraform generation for this node.

Adding a new resource type
--------------------------
Just implement terraform_module() on the GCPNode subclass.
No changes to engine.py, no registry entries.
"""
from __future__ import annotations

import logging
from typing import Any

from core.registry import NODE_REGISTRY
from deploy.graph_resolver import resolve_graph
from nodes.base_node import TFBlock, TFModule
from terraform_gen.hcl_writer import blocks_to_hcl, block_to_hcl

logger = logging.getLogger(__name__)

_UI_ONLY_TYPES = {"vpcGroup", "groupBox", ""}

# ── Root-level standard variables ─────────────────────────────────────────────

_ROOT_VARIABLES: list[TFBlock] = [
    TFBlock(
        block_type="variable", labels=["project_id"],
        body={"description": "The GCP project ID", "type": "string"},
    ),
    TFBlock(
        block_type="variable", labels=["region"],
        body={"description": "Default GCP region", "type": "string", "default": ""},
    ),
    TFBlock(
        block_type="variable", labels=["environment"],
        body={"description": "Deployment environment (dev/staging/prod)", "type": "string", "default": "dev"},
    ),
]


def _versions_tf() -> str:
    return """\
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
"""


def _tfvars(project: str, region: str) -> str:
    return f"""\
# terraform.tfvars — fill in before running terraform apply

project_id  = "{project}"
region      = "{region}"
environment = "dev"
"""


def _module_variables_tf(variables: list[TFBlock], region: str) -> str:
    """Write variables.tf for a module — deduplicated."""
    seen:   set[str]     = set()
    unique: list[TFBlock] = []
    for v in variables:
        key = v.labels[0] if v.labels else ""
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return blocks_to_hcl(unique) if unique else ""


# ── Main generator ────────────────────────────────────────────────────────────

def generate_terraform(
    nodes:   list[dict],
    edges:   list[dict],
    project: str,
    region:  str = "us-central1",
) -> dict[str, str]:
    """
    Generate a complete Terraform workspace using module-per-resource layout.

    Returns a flat dict of relative file paths → content:
        {
            "versions.tf":                   str,
            "variables.tf":                  str,
            "terraform.tfvars":              str,
            "main.tf":                       str,
            "outputs.tf":                    str,
            "modules/my_sa/main.tf":         str,
            "modules/my_sa/variables.tf":    str,
            "modules/my_sa/outputs.tf":      str,
            "modules/my_cr/main.tf":         str,
            ...
        }
    """
    ctx = resolve_graph(nodes, edges, NODE_REGISTRY)

    # ── Per-node module generation ─────────────────────────────────────────────
    module_calls:   list[str] = []   # root main.tf module{} blocks
    root_outputs:   list[str] = []   # root outputs.tf output{} blocks
    module_files:   dict[str, str] = {}
    unsupported:    list[str] = []

    for node in nodes:
        ntype = node.get("type", "")
        if ntype in _UI_ONLY_TYPES:
            continue

        cls = NODE_REGISTRY.get(ntype)
        if cls is None:
            unsupported.append(ntype)
            logger.warning("generate_terraform: unknown node type '%s' — skipped", ntype)
            continue

        node_inst = cls(node_id=node["id"], label=node.get("label", ""))
        node_ctx  = ctx.get(node["id"], {"node": node})

        try:
            module: TFModule | None = node_inst.terraform_module(
                ctx=node_ctx, project=project, region=region, all_nodes=nodes,
            )
        except Exception as exc:
            logger.error("terraform_module() failed for %s (%s): %s",
                         node.get("label", node["id"]), ntype, exc, exc_info=True)
            module = None

        if module is None:
            unsupported.append(ntype)
            continue

        tf_id     = module.module_name
        mod_path  = f"modules/{tf_id}"

        # ── Write module files ─────────────────────────────────────────────────
        # main.tf — resources + data sources
        main_parts = []
        if module.data:
            main_parts.append("# ── Data Sources ──────────────────────────────")
            main_parts.append(blocks_to_hcl(module.data))
        if module.resources:
            main_parts.append("# ── Resources ────────────────────────────────")
            main_parts.append(blocks_to_hcl(module.resources))
        module_files[f"{mod_path}/main.tf"] = "\n\n".join(main_parts) if main_parts else "# No resources\n"

        # variables.tf
        if module.variables:
            module_files[f"{mod_path}/variables.tf"] = _module_variables_tf(module.variables, region)

        # outputs.tf
        if module.outputs:
            module_files[f"{mod_path}/outputs.tf"] = blocks_to_hcl(module.outputs)

        # ── Root main.tf: module{} call block ─────────────────────────────────
        # module variables are passed as key = value pairs
        call_body_lines = [f'  source = "./{mod_path}"']
        call_body_lines.append(f'  project_id = var.project_id')
        call_body_lines.append(f'  region     = var.region')
        for var_name, var_value in module.call_vars.items():
            call_body_lines.append(f"  {var_name} = {var_value}")
        module_calls.append(
            f'# {node.get("label", tf_id)} ({ntype})\n'
            f'module "{tf_id}" {{\n'
            + "\n".join(call_body_lines)
            + "\n}"
        )

        # ── Root outputs.tf: re-export each module output ─────────────────────
        for out_block in module.outputs:
            out_name = out_block.labels[0] if out_block.labels else ""
            if out_name:
                desc = out_block.body.get("description", "")
                root_outputs.append(
                    f'output "{tf_id}__{out_name}" {{\n'
                    f'  description = "{desc}"\n'
                    f'  value       = module.{tf_id}.{out_name}\n'
                    f'}}'
                )

    # ── Root main.tf ───────────────────────────────────────────────────────────
    main_tf_parts = []
    if module_calls:
        main_tf_parts.extend(module_calls)
    if unsupported:
        skipped = sorted(set(unsupported))
        main_tf_parts.append(
            "# The following node types have no terraform_module() and were skipped:\n"
            + "".join(f"#   - {t}\n" for t in skipped)
        )
    main_tf = "\n\n".join(main_tf_parts) if main_tf_parts else "# No modules generated\n"

    # ── Root variables.tf ──────────────────────────────────────────────────────
    root_vars_blocks = list(_ROOT_VARIABLES)
    # Inject actual region default
    root_vars_blocks[1] = TFBlock(
        block_type="variable", labels=["region"],
        body={"description": "Default GCP region", "type": "string", "default": region},
    )
    root_variables_tf = blocks_to_hcl(root_vars_blocks)

    # ── Root outputs.tf ────────────────────────────────────────────────────────
    root_outputs_tf = "\n\n".join(root_outputs) if root_outputs else "# No outputs defined\n"

    return {
        "versions.tf":      _versions_tf(),
        "variables.tf":     root_variables_tf,
        "terraform.tfvars": _tfvars(project, region),
        "main.tf":          main_tf,
        "outputs.tf":       root_outputs_tf,
        **module_files,
    }


# ── Preview summary ────────────────────────────────────────────────────────────

def generate_terraform_summary(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    from nodes.base_node import GCPNode as _Base
    summary: list[dict] = []
    for node in nodes:
        ntype = node.get("type", "")
        if ntype in _UI_ONLY_TYPES:
            continue
        cls       = NODE_REGISTRY.get(ntype)
        supported = cls is not None and cls.terraform_module is not _Base.terraform_module
        summary.append({
            "node_id":   node["id"],
            "label":     node.get("label", node["id"]),
            "type":      ntype,
            "supported": supported,
        })
    return {
        "total":     len(summary),
        "supported": sum(1 for s in summary if s["supported"]),
        "skipped":   sum(1 for s in summary if not s["supported"]),
        "nodes":     summary,
    }