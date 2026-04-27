"""
codegen/schema_to_nodes.py — VCO node codegen from Pulumi schema + overlays.
See module docstring inside for full usage.
"""
from __future__ import annotations

import argparse, json, re, sys, textwrap
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


# ── naming ────────────────────────────────────────────────────────────────────

def _to_class_name(pulumi_type: str) -> str:
    module, _, resource = pulumi_type.partition(".")
    mod_words = re.sub(r"([A-Z])", r"_\1", module).strip("_").split("_")
    res_words = re.sub(r"([A-Z])", r"_\1", resource).strip("_").split("_")
    return "".join(w.capitalize() for w in mod_words + res_words) + "Node"

def _to_filename(pulumi_type: str) -> str:
    module, _, resource = pulumi_type.partition(".")
    snake = re.sub(r"([A-Z])", r"_\1", resource).strip("_").lower()
    return f"{module}_{snake}.py"

def _overlay_filename(pulumi_type: str) -> str:
    return _to_filename(pulumi_type).replace(".py", ".yaml")


# ── schema parsing ─────────────────────────────────────────────────────────────

_ALWAYS_SKIP   = frozenset({"project","labels","annotations","conditions",
                             "etag","selfLink","fingerprint","uid","name"})
_COMPLEX_TYPES = frozenset({"object","array"})

def _pulumi_keys(pulumi_type: str) -> list[str]:
    module, _, resource = pulumi_type.partition(".")
    lower = re.sub(r"([A-Z])", r"_\1", resource).strip("_").lower()
    return [
        f"gcp:{module}/{lower}:{resource}",
        f"gcp:{module}/{resource.lower()}:{resource}",
        f"gcp:{module}/{lower.replace('_','')}:{resource}",
    ]

def extract_resource(schema: dict, pulumi_type: str) -> dict | None:
    resources = schema.get("resources", {})
    for k in _pulumi_keys(pulumi_type):
        if k in resources:
            return resources[k]
    needle = pulumi_type.lower().replace(".", "")
    for k, v in resources.items():
        if needle in k.lower().replace(":","").replace("/","").replace("_",""):
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
    if prop.get("enum"):       return "select"
    t = prop.get("type", "string")
    if t == "integer":         return "number"
    if t == "boolean":         return "boolean"
    if "yaml" in name.lower(): return "yaml"
    if "json" in name.lower(): return "json"
    return "text"

def _build_params_schema(resource_def: dict, overlay: dict) -> list[dict]:
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

    result = [{"key":"name","label":"Resource Name","type":"text",
               "default":"","placeholder":"my-resource"}]
    result += overlay_params
    result += [p for k, p in auto.items() if k not in overlay_keys]
    return result


# ── body normalisation ────────────────────────────────────────────────────────

def _norm(raw: str | None, default: str) -> str:
    """Dedent a YAML block scalar so the Jinja indent filter works cleanly."""
    if not raw:
        return default
    return textwrap.dedent(raw).strip()


# ── code generation ────────────────────────────────────────────────────────────

def generate_node(pulumi_type, resource_def, overlay, defaults, env) -> str:
    module, _, resource = pulumi_type.partition(".")
    class_name = overlay.get("class_name") or _to_class_name(pulumi_type)
    description = (
        overlay.get("description")
        or resource_def.get("description","").split(".")[0][:120]
        or class_name
    )

    # If overlay supplies "pulumi_program_method" — a complete method string —
    # we use that and suppress the generated skeleton.
    # Legacy: "extra_methods" containing "def pulumi_program" also suppresses
    # the skeleton; the method is rendered via extra_class_members.
    raw_pm    = overlay.get("pulumi_program_method", "")
    raw_extra = overlay.get("extra_methods", "")        # legacy key
    raw_ecm   = overlay.get("extra_class_members", "")  # preferred key
    has_custom = bool(raw_pm) or ("def pulumi_program" in raw_extra)

    # Resolve extra_class_members: dedicated key wins, then legacy fallback
    if raw_ecm:
        ecm = raw_ecm
    elif raw_extra:
        ecm = _strip_pulumi_program_from_extra(raw_extra) if raw_pm else raw_extra
    else:
        ecm = ""

    ctx = {
        "pulumi_type":    pulumi_type,
        "pulumi_module":  module,
        "pulumi_class":   resource,
        "class_name":     class_name,
        "description":    description,
        "category":       overlay.get("category",   defaults.get("category",   "General")),
        "node_color":     overlay.get("node_color",  defaults.get("node_color", "#1e293b")),
        "icon":           overlay.get("icon",        defaults.get("icon",       "box")),
        "url_field":      overlay.get("url_field"),
        "params_schema":  _build_params_schema(resource_def, overlay),
        "inputs":         overlay.get("inputs",  []),
        "outputs":        overlay.get("outputs", []),
        "resolve_edges_body": _norm(overlay.get("resolve_edges_body"), "return False"),
        "dag_deps_body":      _norm(overlay.get("dag_deps_body"),       "return []"),
        "live_outputs_body":  _norm(overlay.get("live_outputs_body"),   "return dict(pulumi_outputs)"),
        "log_source_body":    _norm(overlay.get("log_source_body"),     "return None"),
        "has_custom_pulumi_program": has_custom,
        "pulumi_program_method":     _norm(raw_pm, ""),
        "extra_class_members":       _norm(ecm, ""),
    }
    return env.get_template("node_template.py.j2").render(**ctx)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate VCO node .py files from Pulumi GCP schema + overlays")
    p.add_argument("--schema",       required=True)
    p.add_argument("--resources",    nargs="*", default=[])
    p.add_argument("--all-overlays", action="store_true",
                   help="Generate for every *.yaml overlay file")
    p.add_argument("--all-schema",   action="store_true",
                   help="Generate for EVERY resource in the schema (overlay optional)")
    p.add_argument("--overlays",     default="codegen/overlays/")
    p.add_argument("--out",          default="nodes/")
    p.add_argument("--templates",    default="codegen/templates/")
    p.add_argument("--dry-run",      action="store_true")
    args = p.parse_args()

    schema_path = Path(args.schema)
    if not schema_path.exists():
        sys.exit(f"[ERROR] Schema not found: {schema_path}\n"
                 "Run: pulumi package get-schema gcp > codegen/schema.json")
    schema = json.loads(schema_path.read_text())

    overlay_dir = Path(args.overlays)
    out_dir     = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    defaults: dict = {}
    df = overlay_dir / "_defaults.yaml"
    if df.exists():
        defaults = yaml.safe_load(df.read_text()) or {}

    env = Environment(
        loader=FileSystemLoader(str(args.templates)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pyrepr"] = repr

    # ── resource list resolution ──────────────────────────────────────────────
    resources: list[str] = list(args.resources)

    if args.all_schema:
        resources = _all_resource_types(schema)
        print(f"[INFO] --all-schema: {len(resources)} resources found")

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
        sys.exit("[ERROR] No resources. Use --resources, --all-overlays, or --all-schema.")

    # ── generate ──────────────────────────────────────────────────────────────
    ok = fail = skip = 0
    for ptype in resources:
        rdef = extract_resource(schema, ptype)
        if rdef is None:
            print(f"[WARN]  {ptype:48s} not in schema — skip", file=sys.stderr)
            skip += 1
            continue

        ov_file = overlay_dir / _overlay_filename(ptype)
        overlay  = yaml.safe_load(ov_file.read_text()) if ov_file.exists() else {}

        try:
            code     = generate_node(ptype, rdef, overlay or {}, defaults, env)
            out_path = out_dir / _to_filename(ptype)
            if args.dry_run:
                print(f"\n{'─'*70}\n# {out_path}\n{'─'*70}\n{code}")
            else:
                out_path.write_text(code)
                flag = "✦" if ov_file.exists() else "·"
                print(f"[OK] {flag}  {ptype:48s} → {out_path.name}")
            ok += 1
        except Exception as exc:
            import traceback
            print(f"[FAIL]  {ptype:48s} → {exc}", file=sys.stderr)
            if args.dry_run:
                traceback.print_exc()
            fail += 1

    print(f"\n{'─'*55}")
    print(f"Generated: {ok}  |  Skipped: {skip}  |  Failed: {fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()