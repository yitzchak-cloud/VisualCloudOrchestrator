"""
terraform_gen/engine.py
========================
Terraform workspace generator.

How it works
------------
Each GCPNode subclass defines two things:

  @property
  def terraform_dir(self) -> Path | None:
      return Path(__file__).parent / "terraform"

  def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict[str, str]:
      return {"name": f'"{_resource_name(self.node_dict)}"', ...}

engine.py does exactly two things:
  1. Reads terraform_dir from each node → copies all *.tf files verbatim
     into the output zip as  modules/<module_type>/
  2. Calls terraform_call_vars() → writes one module{} call block
     in root main.tf

No HCL generation, no TFBlock, no TFModule needed here.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from core.registry import NODE_REGISTRY
from deploy.graph_resolver import resolve_graph
from nodes.base_node import _resource_name, _tf_name

logger = logging.getLogger(__name__)

_UI_ONLY_TYPES = {"vpcGroup", "groupBox", ""}


# ── Root file builders ─────────────────────────────────────────────────────────

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


def _root_variables_tf(region: str) -> str:
    return f"""\
variable "project_id" {{
  description = "The GCP project ID"
  type        = string
}}

variable "region" {{
  description = "Default GCP region"
  type        = string
  default     = "{region}"
}}

variable "environment" {{
  description = "Deployment environment (dev/staging/prod)"
  type        = string
  default     = "dev"
}}
"""


def _tfvars(project: str, region: str) -> str:
    return f"""\
# terraform.tfvars — edit before running terraform apply

project_id  = "{project}"
region      = "{region}"
environment = "dev"
"""


def _build_module_call(
    instance_name: str,
    module_type:   str,
    label:         str,
    ntype:         str,
    call_vars:     dict[str, str],
) -> str:
    """
    Writes one module{} call block in root main.tf:

      # My Service (CloudRunNode)
      module "cr_my_service" {
        source     = "./modules/cloud_run"
        project_id = var.project_id
        region     = var.region
        name       = "my-service"
        sa_email   = module.sa_worker.email
      }
    """
    lines = [
        f"# {label} ({ntype})",
        f'module "{instance_name}" {{',
        f'  source     = "./modules/{module_type}"',
        f'  project_id = var.project_id',
        f'  region     = var.region',
    ]
    for k, v in call_vars.items():
        lines.append(f"  {k} = {v}")
    lines.append("}")
    return "\n".join(lines)


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_terraform(
    nodes:   list[dict],
    edges:   list[dict],
    project: str,
    region:  str = "us-central1",
) -> dict[str, str]:
    """
    Generate a complete Terraform workspace.

    Returns: { relative_file_path: content }
      versions.tf, variables.tf, terraform.tfvars, main.tf, outputs.tf
      modules/<type>/main.tf          ← copied from node's terraform_dir
      modules/<type>/variables.tf     ← copied from node's terraform_dir
      modules/<type>/outputs.tf       ← copied from node's terraform_dir
    """
    ctx = resolve_graph(nodes, edges, NODE_REGISTRY)

    module_calls:   list[str]       = []
    root_outputs:   list[str]       = []
    copied_modules: set[str]        = set()   # module_type already copied
    module_files:   dict[str, str]  = {}
    unsupported:    list[str]       = []

    for node in nodes:
        ntype = node.get("type", "")
        if ntype in _UI_ONLY_TYPES:
            continue

        cls = NODE_REGISTRY.get(ntype)
        if cls is None:
            unsupported.append(f"{node.get('label', node['id'])} ({ntype})")
            continue

        # Instantiate node (cheap — no I/O)
        node_inst = cls(node_id=node["id"], label=node.get("label", ""))
        node_ctx  = ctx.get(node["id"], {"node": node})

        # ── 1. Get the static HCL module directory ────────────────────────────
        tf_dir = node_inst.terraform_dir
        if tf_dir is None:
            unsupported.append(f"{node.get('label', node['id'])} ({ntype})")
            continue

        if not tf_dir.exists():
            logger.warning(
                "terraform_dir not found for %s (%s): %s", node["id"], ntype, tf_dir
            )
            unsupported.append(f"{node.get('label', node['id'])} ({ntype})")
            continue

        # module_type = directory name (e.g. "cloud_run", "pubsub_topic")
        module_type = tf_dir.name

        # ── 2. Copy static module files (once per module type) ────────────────
        if module_type not in copied_modules:
            copied_modules.add(module_type)
            for tf_file in sorted(tf_dir.glob("*.tf")):
                dest_key = f"modules/{module_type}/{tf_file.name}"
                module_files[dest_key] = tf_file.read_text(encoding="utf-8")
                logger.debug("Copied static module file: %s", dest_key)

        # ── 3. Build per-instance call_vars ───────────────────────────────────
        try:
            call_vars = node_inst.terraform_call_vars(node_ctx, project, region, nodes)
        except Exception as exc:
            logger.error(
                "terraform_call_vars failed for %s (%s): %s",
                node.get("label"), ntype, exc, exc_info=True,
            )
            unsupported.append(f"{node.get('label', node['id'])} ({ntype})")
            continue

        if not call_vars:
            # Node returned {} → explicitly opted out
            continue

        # ── 4. Build module{} call block ──────────────────────────────────────
        prefix        = node_inst.terraform_instance_prefix
        instance_name = f"{prefix}_{_tf_name(node)}"
        label         = node.get("label", node["id"])

        module_calls.append(
            _build_module_call(instance_name, module_type, label, ntype, call_vars)
        )

        # ── 5. Root outputs: re-export standard outputs ───────────────────────
        # Detect what outputs exist in the module's outputs.tf
        outputs_tf = tf_dir / "outputs.tf"
        if outputs_tf.exists():
            import re
            src = outputs_tf.read_text(encoding="utf-8")
            out_names = re.findall(r'output\s+"([^"]+)"', src)
            for out_name in out_names:
                root_outputs.append(
                    f'output "{instance_name}__{out_name}" {{\n'
                    f'  description = "{label} {out_name}"\n'
                    f'  value       = module.{instance_name}.{out_name}\n'
                    f'}}'
                )

    # ── Assemble root main.tf ──────────────────────────────────────────────────
    parts = list(module_calls)
    if unsupported:
        skipped = sorted(set(unsupported))
        parts.append(
            "# Nodes without Terraform support (skipped):\n"
            + "".join(f"#   - {u}\n" for u in skipped)
        )

    return {
        "versions.tf":      _versions_tf(),
        "variables.tf":     _root_variables_tf(region),
        "terraform.tfvars": _tfvars(project, region),
        "main.tf":          "\n\n".join(parts) if parts else "# No modules generated\n",
        "outputs.tf":       "\n\n".join(root_outputs) if root_outputs else "# No outputs\n",
        **module_files,
    }


# ── Preview summary ────────────────────────────────────────────────────────────

def generate_terraform_summary(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    summary: list[dict] = []
    for node in nodes:
        ntype = node.get("type", "")
        if ntype in _UI_ONLY_TYPES:
            continue
        cls = NODE_REGISTRY.get(ntype)
        supported = False
        if cls is not None:
            try:
                inst = cls(node_id=node["id"], label="")
                supported = inst.terraform_dir is not None
            except Exception:
                pass
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