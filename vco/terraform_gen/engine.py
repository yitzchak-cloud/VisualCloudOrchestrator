"""
terraform_gen/engine.py
========================
Main entry point for Terraform code generation.

Call generate_terraform(nodes, edges, project, region) to get back a dict
mapping filename → file content.  These files are ready to be zipped and
downloaded.

Generated file structure (industry-standard layout):
  main.tf          — provider + resource blocks
  variables.tf     — all input variables
  terraform.tfvars — default variable values (fill in before running)
  outputs.tf       — all output blocks
  versions.tf      — required_providers + terraform version constraint

All file contents are pure HCL — no Pulumi, no Python, no magic.
"""
from __future__ import annotations

import logging
from typing import Any

from .context_builder import build_tf_context
from .generators.base import GeneratorResult, TFBlock
from .generators.registry import TF_GENERATOR_REGISTRY
from .hcl_writer import blocks_to_hcl, block_to_hcl

logger = logging.getLogger(__name__)


# ── Fixed Terraform variables every GCP project needs ─────────────────────────

_STANDARD_VARIABLES: list[TFBlock] = [
    TFBlock(
        block_type="variable",
        labels=["project_id"],
        body={
            "description": "The GCP project ID",
            "type":        "string",
        },
    ),
    TFBlock(
        block_type="variable",
        labels=["region"],
        body={
            "description": "Default GCP region for all resources",
            "type":        "string",
            "default":     "__REGION__",   # replaced at render time
        },
    ),
    TFBlock(
        block_type="variable",
        labels=["environment"],
        body={
            "description": "Deployment environment label (dev / staging / prod)",
            "type":        "string",
            "default":     "dev",
        },
    ),
]


def _versions_tf(project: str, region: str) -> str:
    return f"""\
terraform {{
  required_version = ">= 1.5.0"

  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = "~> 5.0"
    }}
  }}
}}

provider "google" {{
  project = var.project_id
  region  = var.region
}}
"""


def _tfvars(project: str, region: str) -> str:
    return f"""\
# terraform.tfvars
# Fill in the values below and run:  terraform init && terraform apply

project_id  = "{project}"
region      = "{region}"
environment = "dev"
"""


def _variables_tf(extra_vars: list[TFBlock], region: str) -> str:
    # Deduplicate by label[0]
    seen: set[str] = set()
    unique: list[TFBlock] = []
    for v in _STANDARD_VARIABLES + extra_vars:
        key = v.labels[0] if v.labels else ""
        if key not in seen:
            seen.add(key)
            if key == "region":
                # Replace placeholder with actual region value
                v = TFBlock(
                    block_type="variable",
                    labels=["region"],
                    body={
                        "description": "Default GCP region for all resources",
                        "type":        "string",
                        "default":     region,
                    },
                )
            unique.append(v)
    return blocks_to_hcl(unique)


def region_placeholder() -> str:
    # Used internally — replaced with actual region string during generation
    return "__REGION_PLACEHOLDER__"


def generate_terraform(
    nodes:   list[dict],
    edges:   list[dict],
    project: str,
    region:  str = "us-central1",
) -> dict[str, str]:
    """
    Generate a complete Terraform workspace from the VCO graph.

    Returns:
        {
            "main.tf":          <str>,
            "variables.tf":     <str>,
            "terraform.tfvars": <str>,
            "outputs.tf":       <str>,
            "versions.tf":      <str>,
        }
    """
    ctx = build_tf_context(nodes, edges)

    all_resources: list[TFBlock] = []
    all_variables: list[TFBlock] = []
    all_data:      list[TFBlock] = []
    all_outputs:   list[TFBlock] = []

    unknown_types: list[str] = []

    for node in nodes:
        ntype = node.get("type", "")

        # Skip UI-only / group nodes
        if ntype in ("vpcGroup", "groupBox", ""):
            continue

        generator = TF_GENERATOR_REGISTRY.get(ntype)
        if generator is None:
            unknown_types.append(ntype)
            logger.warning("No TF generator for node type: %s — skipped", ntype)
            continue

        try:
            result: GeneratorResult = generator.generate(
                node=node,
                ctx=ctx.get(node["id"], {}),
                project=project,
                region=region,
                all_nodes=nodes,
                edges=edges,
            )
            all_resources.extend(result.resources)
            all_variables.extend(result.variables)
            all_data.extend(result.data)
            all_outputs.extend(result.outputs)
        except Exception as exc:
            logger.error(
                "TF generator failed for %s (%s): %s",
                node.get("label", node["id"]), ntype, exc, exc_info=True,
            )

    # ── Assemble main.tf ──────────────────────────────────────────────────────
    main_parts: list[str] = []

    if all_data:
        main_parts.append("# ── Data Sources ─────────────────────────────────────────────────────────")
        main_parts.append(blocks_to_hcl(all_data))

    if all_resources:
        main_parts.append("# ── Resources ────────────────────────────────────────────────────────────")
        main_parts.append(blocks_to_hcl(all_resources))

    if unknown_types:
        main_parts.append(
            "# The following node types have no Terraform generator and were skipped:\n"
            + "".join(f"#   - {t}\n" for t in sorted(set(unknown_types)))
        )

    main_tf_content = "\n\n".join(main_parts) if main_parts else "# No resources generated\n"

    # ── Assemble variables.tf ─────────────────────────────────────────────────
    vars_tf = _variables_tf(all_variables, region)

    # ── Assemble outputs.tf ───────────────────────────────────────────────────
    outputs_tf = blocks_to_hcl(all_outputs) if all_outputs else "# No outputs defined\n"

    return {
        "versions.tf":      _versions_tf(project, region),
        "variables.tf":     vars_tf,
        "terraform.tfvars": _tfvars(project, region),
        "main.tf":          main_tf_content,
        "outputs.tf":       outputs_tf,
    }


def generate_terraform_summary(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """
    Return a lightweight summary of what *would* be generated
    (used for the API preview endpoint — no HCL text, just metadata).
    """
    ctx = build_tf_context(nodes, edges)
    summary: list[dict] = []

    for node in nodes:
        ntype = node.get("type", "")
        if ntype in ("vpcGroup", "groupBox", ""):
            continue
        generator = TF_GENERATOR_REGISTRY.get(ntype)
        summary.append({
            "node_id":    node["id"],
            "label":      node.get("label", node["id"]),
            "type":       ntype,
            "supported":  generator is not None,
        })

    return {
        "total":     len(summary),
        "supported": sum(1 for s in summary if s["supported"]),
        "skipped":   sum(1 for s in summary if not s["supported"]),
        "nodes":     summary,
    }
