"""
codegen/schema_to_nodes.py
--------------------------
Phase 1+2 codegen: reads Pulumi GCP schema + YAML overlays → generates node .py files.

Usage
-----
  pulumi package get-schema gcp > codegen/schema.json

  # specific resources
  python codegen/schema_to_nodes.py --schema codegen/schema.json \
      --resources cloudrunv2.Service cloudrunv2.Job workflows.Workflow

  # all resources that have an overlay
  python codegen/schema_to_nodes.py --schema codegen/schema.json --all-overlays

  # every resource in the schema (overlay optional — base skeleton used if missing)
  python codegen/schema_to_nodes.py --schema codegen/schema.json --all-schema

  # preview without writing files
  python codegen/schema_to_nodes.py --schema codegen/schema.json \
      --resources pubsub.Topic --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


# ── naming helpers ─────────────────────────────────────────────────────────────

def _to_class_name(pulumi_type: str) -> str:
    """'cloudrunv2.Service' → 'CloudRunV2ServiceNode'"""
    module, _, resource = pulumi_type.partition(".")
    mod_words = re.sub(r"([A-Z])", r"_\1", module).strip("_").split("_")
    res_words = re.sub(r"([A-Z])", r"_\1", resource).strip("_").split("_")
    return "".join(w.capitalize() for w in mod_words + res_words) + "Node"


def _to_filename(pulumi_type: str) -> str:
    """'cloudrunv2.Service' → 'cloudrunv2_service.py'"""
    module, _, resource = pulumi_type.partition(".")
    snake = re.sub(r"([A-Z])", r"_\1", resource).strip("_").lower()
    return f"{module}_{snake}.py"


def _overlay_filename(pulumi_type: str) -> str:
    return _to_filename(pulumi_type).replace(".py", ".yaml")


# ── schema parsing ─────────────────────────────────────────────────────────────

_ALWAYS_SKIP   = frozenset({
    "project", "labels", "annotations", "conditions",
    "etag", "selfLink", "fingerprint", "uid", "name",
})
_COMPLEX_TYPES = frozenset({"object", "array"})


def _pulumi_keys(pulumi_type: str) -> list[str]:
    module, _, resource = pulumi_type.partition(".")
    lower = re.sub(r"([A-Z])", r"_\1", resource).strip("_").lower()
    return [
        f"gcp:{module}/{lower}:{resource}",
        f"gcp:{module}/{resource.lower()}:{resource}",
        f"gcp:{module}/{lower.replace('_', '')}:{resource}",
    ]


def extract_resource(schema: dict, pulumi_type: str) -> dict | None:
    resources = schema.get("resources", {})
    for k in _pulumi_keys(pulumi_type):
        if k in resources:
            return resources[k]
    # fallback: substring search
    needle = pulumi_type.lower().replace(".", "")
    for k, v in resources.items():
        if needle in k.lower().replace(":", "").replace("/", "").replace("_", ""):
            return v
    return None


def _all_resource_types(schema: dict) -> list[str]:
    result = []
    for key in schema.get("resources", {}):
        m = re.match(r"gcp:([^/]+)/[^:]+:(.+)$", key)
        if m:
            result.append(f"{m.group(1)}.{m.group(2)}")
    return result


def _infer_ui_type(name: str, prop: dict) -> str:
    if prop.get("enum"):        return "select"
    t = prop.get("type", "string")
    if t == "integer":          return "number"
    if t == "boolean":          return "boolean"
    if "yaml" in name.lower():  return "yaml"
    if "json" in name.lower():  return "json"
    return "text"


def _build_params_schema(resource_def: dict, overlay: dict) -> list[dict]:
    """
    Merge auto-detected params from Pulumi schema with overlay overrides.
    Order: name (always first) → overlay params → auto-detected remainder.
    """
    props = resource_def.get("inputProperties", {})
    auto: dict[str, dict] = {}
    for pname, pschema in props.items():
        if pname in _ALWAYS_SKIP:
            continue
        if pschema.get("type") in _COMPLEX_TYPES or "$ref" in pschema:
            continue
        entry: dict[str, Any] = {
            "key":     pname,
            "label":   re.sub(r"([A-Z])", r" \1", pname).strip().title(),
            "type":    _infer_ui_type(pname, pschema),
            "default": pschema.get("default", ""),
        }
        if entry["type"] == "select":
            entry["options"] = [str(e) for e in pschema.get("enum", [])]
        desc = pschema.get("description", "")
        if desc:
            entry["description"] = desc.split(".")[0][:120]
        auto[pname] = entry

    overlay_params = overlay.get("params_schema", [])
    overlay_keys   = {p["key"] for p in overlay_params}

    result = [{"key": "name", "label": "Resource Name",
               "type": "text", "default": "", "placeholder": "my-resource"}]
    result += overlay_params
    result += [p for k, p in auto.items() if k not in overlay_keys]
    return result


# ── body normalisation ─────────────────────────────────────────────────────────

def _norm(raw: str | None, default: str) -> str:
    """
    Dedent a YAML block scalar so the Jinja2 `indent` filter can re-indent
    it cleanly to the correct Python indentation level.
    """
    if not raw:
        return default
    return textwrap.dedent(raw).strip()


def _strip_pulumi_program(text: str) -> str:
    """
    Remove a 'def pulumi_program(...)' method block from a string.
    Used to avoid duplicate method definitions when the overlay supplies
    both extra_class_members and pulumi_program_method.
    """
    if "def pulumi_program" not in text:
        return text
    lines       = text.splitlines()
    result      = []
    inside      = False
    base_indent = 0
    for line in lines:
        stripped = line.lstrip()
        if not inside and stripped.startswith("def pulumi_program"):
            inside      = True
            base_indent = len(line) - len(stripped)
            continue
        if inside:
            current = len(line) - len(line.lstrip()) if line.strip() else 999
            if line.strip() == "" or current > base_indent:
                continue      # still inside the method body
            else:
                inside = False  # method ended — fall through to append
        result.append(line)
    return "\n".join(result)


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

    class_name  = overlay.get("class_name") or _to_class_name(pulumi_type)
    description = (
        overlay.get("description")
        or resource_def.get("description", "").split(".")[0][:120]
        or class_name
    )

    # ── pulumi_program resolution ─────────────────────────────────────────────
    # Priority:
    #   1. pulumi_program_method  — full method body (preferred, clean)
    #   2. extra_methods          — legacy key; may contain def pulumi_program
    #   3. extra_class_members    — class-level helpers (class vars, @staticmethod)
    # If a custom pulumi_program exists → suppress the generated skeleton.

    raw_pm    = overlay.get("pulumi_program_method", "")   # preferred
    raw_extra = overlay.get("extra_methods", "")            # legacy
    raw_ecm   = overlay.get("extra_class_members", "")     # helpers / class vars

    has_custom_pulumi = bool(raw_pm) or ("def pulumi_program" in raw_extra)

    # Resolve what goes into extra_class_members in the template
    if raw_ecm:
        # dedicated key — use as-is (no pulumi_program stripping needed)
        ecm = raw_ecm
    elif raw_extra:
        # legacy: extra_methods had everything; strip pulumi_program if
        # it's already supplied via pulumi_program_method to avoid duplicate
        ecm = _strip_pulumi_program(raw_extra) if raw_pm else raw_extra
    else:
        ecm = ""

    ctx = {
        # identity
        "pulumi_type":   pulumi_type,
        "pulumi_module": module,
        "pulumi_class":  resource,
        "class_name":    class_name,
        # UI metadata
        "description":   description,
        "category":      overlay.get("category",   defaults.get("category",   "General")),
        "node_color":    overlay.get("node_color",  defaults.get("node_color", "#1e293b")),
        "icon":          overlay.get("icon",        defaults.get("icon",       "box")),
        "url_field":     overlay.get("url_field"),
        "params_schema": _build_params_schema(resource_def, overlay),
        # ports
        "inputs":        overlay.get("inputs",  []),
        "outputs":       overlay.get("outputs", []),
        # method bodies — dedented; template re-indents with `indent` filter
        "resolve_edges_body": _norm(overlay.get("resolve_edges_body"), "return False"),
        "dag_deps_body":      _norm(overlay.get("dag_deps_body"),       "return []"),
        "live_outputs_body":  _norm(overlay.get("live_outputs_body"),   "return dict(pulumi_outputs)"),
        "log_source_body":    _norm(overlay.get("log_source_body"),     "return None"),
        # pulumi_program
        "has_custom_pulumi_program": has_custom_pulumi,
        "pulumi_program_method":     _norm(raw_pm, ""),
        # extra class members (class vars, @staticmethod helpers, etc.)
        "extra_class_members": _norm(ecm, ""),
    }
    return env.get_template("node_template.py.j2").render(**ctx)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate VCO node .py files from Pulumi GCP schema + overlays"
    )
    p.add_argument("--schema",       required=True,
                   help="Path to schema.json (pulumi package get-schema gcp)")
    p.add_argument("--resources",    nargs="*", default=[],
                   help="Explicit pulumi types, e.g. cloudrunv2.Service pubsub.Topic")
    p.add_argument("--all-overlays", action="store_true",
                   help="Generate for every *.yaml file in --overlays/")
    p.add_argument("--all-schema",   action="store_true",
                   help="Generate for EVERY resource in the schema (overlay optional)")
    p.add_argument("--overlays",     default="codegen/overlays/",
                   help="Directory with per-resource YAML overlays")
    p.add_argument("--out",          default="nodes/",
                   help="Output directory for generated .py files")
    p.add_argument("--templates",    default="codegen/templates/",
                   help="Jinja2 templates directory")
    p.add_argument("--dry-run",      action="store_true",
                   help="Print to stdout instead of writing files")
    args = p.parse_args()

    # ── load schema ───────────────────────────────────────────────────────────
    schema_path = Path(args.schema)
    if not schema_path.exists():
        sys.exit(
            f"[ERROR] Schema not found: {schema_path}\n"
            "Run:  pulumi package get-schema gcp > codegen/schema.json"
        )
    schema = json.loads(schema_path.read_text())

    overlay_dir = Path(args.overlays)
    out_dir     = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # ── global defaults ───────────────────────────────────────────────────────
    defaults: dict = {}
    df = overlay_dir / "_defaults.yaml"
    if df.exists():
        defaults = yaml.safe_load(df.read_text()) or {}

    # ── Jinja2 env ────────────────────────────────────────────────────────────
    env = Environment(
        loader=FileSystemLoader(str(args.templates)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pyrepr"] = repr

    # ── resolve resource list ─────────────────────────────────────────────────
    resources: list[str] = list(args.resources)

    if args.all_schema:
        resources = _all_resource_types(schema)
        print(f"[INFO] --all-schema: {len(resources)} resources found in schema")

    elif args.all_overlays:
        for yf in sorted(overlay_dir.glob("*.yaml")):
            if yf.stem.startswith("_"):
                continue
            parts  = yf.stem.split("_")
            module = parts[0]
            res    = "".join(w.capitalize() for w in parts[1:])
            ptype  = f"{module}.{res}"
            if ptype not in resources:
                resources.append(ptype)

    if not resources:
        sys.exit(
            "[ERROR] No resources specified.\n"
            "Use --resources <type...>, --all-overlays, or --all-schema."
        )

    # ── generate ──────────────────────────────────────────────────────────────
    ok = fail = skip = 0
    for ptype in resources:
        rdef = extract_resource(schema, ptype)
        if rdef is None:
            print(f"[WARN]  {ptype:50s} not in schema — skipped", file=sys.stderr)
            skip += 1
            continue

        ov_file = overlay_dir / _overlay_filename(ptype)
        overlay: dict = {}
        if ov_file.exists():
            overlay = yaml.safe_load(ov_file.read_text()) or {}

        try:
            code     = generate_node(ptype, rdef, overlay, defaults, env)
            out_path = out_dir / _to_filename(ptype)
            if args.dry_run:
                print(f"\n{'─'*70}\n# {out_path}\n{'─'*70}\n{code}")
            else:
                out_path.write_text(code)
                flag = "✦" if ov_file.exists() else "·"
                print(f"[OK] {flag}  {ptype:50s} → {out_path.name}")
            ok += 1
        except Exception as exc:
            import traceback
            print(f"[FAIL]  {ptype:50s} → {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            fail += 1

    print(f"\n{'─'*55}")
    print(f"Generated: {ok}  |  Skipped: {skip}  |  Failed: {fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()