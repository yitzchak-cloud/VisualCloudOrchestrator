"""
codegen/schema_to_nodes.py
--------------------------
Phase 1: Parse `pulumi package get-schema gcp` JSON and emit
a base node skeleton for every requested resource type.

Merges with per-resource YAML overlays (Phase 2) to produce
a complete, ready-to-use node .py file.

Usage
-----
  # Dump the schema once (takes ~30 s):
  pulumi package get-schema gcp > codegen/schema.json

  # Generate specific resources:
  python codegen/schema_to_nodes.py \\
      --schema  codegen/schema.json \\
      --resources cloudrunv2.Service cloudrunv2.Job workflows.Workflow \\
      --overlays  codegen/overlays/ \\
      --out       nodes/

  # Generate ALL resources that have an overlay file:
  python codegen/schema_to_nodes.py \\
      --schema  codegen/schema.json \\
      --all-overlays \\
      --overlays codegen/overlays/ \\
      --out      nodes/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


# ── naming helpers ─────────────────────────────────────────────────────────────

def _to_class_name(pulumi_type: str) -> str:
    """
    'cloudrunv2.Service' → 'CloudRunV2ServiceNode'
    'pubsub.Topic'       → 'PubsubTopicNode'
    """
    module, _, resource = pulumi_type.partition(".")
    # split camelCase resource into words
    words = re.sub(r"([A-Z])", r"_\1", resource).strip("_").split("_")
    # capitalise module segments + resource words
    mod_words = re.sub(r"([A-Z])", r"_\1", module).strip("_").split("_")
    return "".join(w.capitalize() for w in mod_words + words) + "Node"


def _to_filename(pulumi_type: str) -> str:
    """
    'cloudrunv2.Service' → 'cloudrunv2_service.py'
    'pubsub.Topic'       → 'pubsub_topic.py'
    """
    module, _, resource = pulumi_type.partition(".")
    resource_snake = re.sub(r"([A-Z])", r"_\1", resource).strip("_").lower()
    return f"{module}_{resource_snake}.py"


def _overlay_filename(pulumi_type: str) -> str:
    return _to_filename(pulumi_type).replace(".py", ".yaml")


# ── schema helpers ─────────────────────────────────────────────────────────────

# Properties the engine always manages — never expose to UI
_ALWAYS_SKIP = frozenset({
    "project", "labels", "annotations", "conditions",
    "etag", "selfLink", "fingerprint", "uid",
})

def _pulumi_key(pulumi_type: str) -> list[str]:
    """
    Return candidate resource keys inside schema["resources"].

    Pulumi GCP schema format:  "gcp:MODULE/LOWER_RESOURCE:Resource"
    e.g. 'cloudrunv2.Service' → 'gcp:cloudrunv2/service:Service'
    """
    module, _, resource = pulumi_type.partition(".")
    resource_lower = re.sub(r"([A-Z])", r"_\1", resource).strip("_").lower()
    return [
        f"gcp:{module}/{resource_lower}:{resource}",
        f"gcp:{module}/{resource.lower()}:{resource}",
        f"gcp:{module}/{resource_lower.replace('_','')}:{resource}",
    ]


def extract_resource(schema: dict, pulumi_type: str) -> dict | None:
    resources = schema.get("resources", {})
    for key in _pulumi_key(pulumi_type):
        if key in resources:
            return resources[key]
    # fallback: substring search
    ltype = pulumi_type.lower().replace(".", "")
    for key, val in resources.items():
        if ltype in key.lower().replace(":", "").replace("/", "").replace("_", ""):
            return val
    return None


def _infer_ui_type(prop_name: str, prop_schema: dict) -> str:
    if prop_schema.get("enum"):
        return "select"
    t = prop_schema.get("type", "string")
    if t == "integer":
        return "number"
    if t == "boolean":
        return "boolean"
    if "yaml" in prop_name.lower():
        return "yaml"
    if "json" in prop_name.lower():
        return "json"
    if prop_schema.get("description", ""):
        desc = prop_schema["description"].lower()
        if "yaml" in desc:
            return "yaml"
    return "text"


def _build_params_schema(resource_def: dict, overlay: dict) -> list[dict]:
    """
    Build the merged params_schema list.

    Priority:
      1. "name" is always first (hardcoded).
      2. Overlay-declared params come next (exact order preserved).
      3. Auto-detected props from Pulumi schema fill in the remainder
         (skipping props already in the overlay or in _ALWAYS_SKIP).
    """
    props: dict = resource_def.get("inputProperties", {})

    # ── auto-detect from schema ───────────────────────────────────────────────
    auto: dict[str, dict] = {}
    for prop_name, prop_schema in props.items():
        if prop_name in _ALWAYS_SKIP or prop_name == "name":
            continue
        entry: dict[str, Any] = {
            "key":     prop_name,
            "label":   re.sub(r"([A-Z])", r" \1", prop_name).strip().title(),
            "type":    _infer_ui_type(prop_name, prop_schema),
            "default": prop_schema.get("default", ""),
        }
        if entry["type"] == "select":
            entry["options"] = [str(e) for e in prop_schema.get("enum", [])]
        desc = prop_schema.get("description", "")
        if desc:
            # keep first sentence only — schema descriptions can be very long
            entry["description"] = desc.split(".")[0][:120]
        auto[prop_name] = entry

    # ── merge ─────────────────────────────────────────────────────────────────
    overlay_params: list[dict] = overlay.get("params_schema", [])
    overlay_keys   = {p["key"] for p in overlay_params}

    result = [
        {"key": "name", "label": "Resource Name",
         "type": "text", "default": "", "placeholder": "my-resource"}
    ]
    result += overlay_params
    result += [p for k, p in auto.items() if k not in overlay_keys]

    return result


# ── code generation ────────────────────────────────────────────────────────────

def generate_node(
    pulumi_type:  str,
    resource_def: dict,
    overlay:      dict,
    defaults:     dict,
    env:          Environment,
) -> str:
    """Render one node .py file from template + schema + overlay."""
    module, _, resource = pulumi_type.partition(".")
    class_name = overlay.get("class_name") or _to_class_name(pulumi_type)
    params     = _build_params_schema(resource_def, overlay)

    # description: overlay wins, then first line of schema description
    description = (
        overlay.get("description")
        or resource_def.get("description", "").split(".")[0][:120]
        or class_name
    )

    ctx = {
        # identity
        "pulumi_type":    pulumi_type,
        "pulumi_module":  module,
        "pulumi_class":   resource,
        "class_name":     class_name,
        # UI metadata
        "description":    description,
        "category":       overlay.get("category",    defaults.get("category",    "General")),
        "node_color":     overlay.get("node_color",  defaults.get("node_color",  "#1e293b")),
        "icon":           overlay.get("icon",        defaults.get("icon",        "box")),
        "url_field":      overlay.get("url_field"),
        "params_schema":  params,
        # ports (Phase 2 — from overlay)
        "inputs":         overlay.get("inputs",  []),
        "outputs":        overlay.get("outputs", []),
        # custom method bodies injected verbatim
        "resolve_edges_body":   overlay.get("resolve_edges_body",   "        return False"),
        "dag_deps_body":        overlay.get("dag_deps_body",        "        return []"),
        "pulumi_program_extra": overlay.get("pulumi_program_extra", ""),
        "live_outputs_body":    overlay.get("live_outputs_body",    "        return dict(pulumi_outputs)"),
        "log_source_body":      overlay.get("log_source_body",      "        return None"),
        # optional free-form extra methods (legacy key still supported)
        "extra_methods":        overlay.get("extra_methods",        ""),
    }
    return env.get_template("node_template.py.j2").render(**ctx)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate VCO node files from Pulumi GCP schema + overlays"
    )
    parser.add_argument("--schema",       required=True,
                        help="Path to schema.json from `pulumi package get-schema gcp`")
    parser.add_argument("--resources",    nargs="*", default=[],
                        help="Pulumi types to generate, e.g. cloudrunv2.Service")
    parser.add_argument("--all-overlays", action="store_true",
                        help="Generate a node for every *.yaml file found in --overlays")
    parser.add_argument("--overlays",     default="codegen/overlays/",
                        help="Directory containing per-resource YAML overlays")
    parser.add_argument("--out",          default="nodes/",
                        help="Output directory for generated .py files")
    parser.add_argument("--templates",    default="codegen/templates/",
                        help="Jinja2 templates directory")
    parser.add_argument("--dry-run",      action="store_true",
                        help="Print generated code to stdout instead of writing files")
    args = parser.parse_args()

    # ── load schema ───────────────────────────────────────────────────────────
    schema_path = Path(args.schema)
    if not schema_path.exists():
        sys.exit(f"[ERROR] Schema file not found: {schema_path}\n"
                 "Run: pulumi package get-schema gcp > codegen/schema.json")
    schema = json.loads(schema_path.read_text())

    # ── directories ───────────────────────────────────────────────────────────
    overlay_dir = Path(args.overlays)
    out_dir     = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # ── global defaults ───────────────────────────────────────────────────────
    defaults: dict = {}
    defaults_file = overlay_dir / "_defaults.yaml"
    if defaults_file.exists():
        defaults = yaml.safe_load(defaults_file.read_text()) or {}

    # ── Jinja2 env ────────────────────────────────────────────────────────────
    env = Environment(
        loader=FileSystemLoader(str(args.templates)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # custom filter: Python repr for embedding in source code
    env.filters["pyrepr"] = repr

    # ── resolve resource list ─────────────────────────────────────────────────
    resources: list[str] = list(args.resources)
    if args.all_overlays:
        for yaml_file in sorted(overlay_dir.glob("*.yaml")):
            if yaml_file.stem.startswith("_"):
                continue
            # convert filename back to pulumi_type: "cloudrunv2_service" → "cloudrunv2.Service"
            stem   = yaml_file.stem                       # cloudrunv2_service
            parts  = stem.split("_")
            module = parts[0]
            res    = "".join(p.capitalize() for p in parts[1:])
            ptype  = f"{module}.{res}"
            if ptype not in resources:
                resources.append(ptype)

    if not resources:
        sys.exit("[ERROR] No resources specified. Use --resources or --all-overlays.")

    # ── generate ──────────────────────────────────────────────────────────────
    ok = fail = skip = 0
    for pulumi_type in resources:
        resource_def = extract_resource(schema, pulumi_type)
        if resource_def is None:
            print(f"[WARN]  {pulumi_type:40s} not found in schema — skipping",
                  file=sys.stderr)
            skip += 1
            continue

        overlay_file = overlay_dir / _overlay_filename(pulumi_type)
        overlay: dict = {}
        if overlay_file.exists():
            overlay = yaml.safe_load(overlay_file.read_text()) or {}

        try:
            code     = generate_node(pulumi_type, resource_def, overlay, defaults, env)
            out_path = out_dir / _to_filename(pulumi_type)
            if args.dry_run:
                print(f"\n{'─'*70}\n# {out_path}\n{'─'*70}")
                print(code)
            else:
                out_path.write_text(code)
                print(f"[OK]    {pulumi_type:40s} → {out_path}")
            ok += 1
        except Exception as exc:
            print(f"[ERROR] {pulumi_type:40s} → {exc}", file=sys.stderr)
            fail += 1

    # ── summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"Generated: {ok}  |  Skipped: {skip}  |  Failed: {fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()