"""
terraform_gen/hcl_writer.py
============================
Converts TFBlock dataclass objects into properly formatted Terraform HCL.

TFBlock is now defined in nodes/base_node.py (single source of truth).
This module imports it from there — no dependency on the old
terraform_gen/generators/ package.

Design principles:
  - Strings that start with "${"  are written as quoted interpolations
  - Bare TF references (var.x, google_type.name.attr) → unquoted
  - Booleans → true / false  (not Python True/False)
  - Numbers  → unquoted
  - Lists    → [ ]
  - Dicts    → nested blocks  { }
  - Keys that start with "_"  are treated as comment lines (skipped as attrs)
  - A non-empty `comment` field on the TFBlock is emitted as `# ...` above
    the block header.
"""
from __future__ import annotations

import re
from typing import Any


def _is_tf_ref(value: str) -> bool:
    """
    True if the string should be written WITHOUT surrounding quotes in HCL.

    - Bare TF references (var.x, google_type.name.attr, data.type.name.attr)
      → bare:   project = var.project_id
    - ${...} interpolations MUST be inside quoted strings:
      value = "${google_pubsub_topic.x.name}"
      → return False (caller wraps in quotes)
    - true / false / null are HCL keywords → bare.
    """
    if not value:
        return False
    if value in ("true", "false", "null"):
        return True
    if value.startswith("${"):
        return False  # interpolation — must be quoted
    parts = value.split(".")
    if (
        len(parts) >= 2
        and re.match(r'^[a-z][a-z0-9_]*$', parts[0])
        and "/" not in value
        and ":" not in value
        and " " not in value
    ):
        return True
    return False


def _format_value(value: Any, indent: int) -> str:
    """Recursively format a Python value as HCL."""
    pad    = "  " * indent
    pad_in = "  " * (indent + 1)

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        if _is_tf_ref(value):
            return value
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    if isinstance(value, list):
        if not value:
            return "[]"
        items = [_format_value(v, indent + 1) for v in value]
        if all(not isinstance(v, (dict, list)) for v in value):
            joined = ", ".join(items)
            if len(joined) < 80:
                return f"[{joined}]"
        lines = [f"{pad_in}{item}" for item in items]
        return "[\n" + ",\n".join(lines) + f"\n{pad}]"

    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if k.startswith("_"):
                lines.append(f"{pad_in}{v}")
                continue
            formatted_v = _format_value(v, indent + 1)
            if isinstance(v, dict):
                lines.append(f"{pad_in}{k} {{")
                for ik, iv in v.items():
                    if ik.startswith("_"):
                        lines.append(f"{pad_in}  {iv}")
                        continue
                    fv = _format_value(iv, indent + 2)
                    if isinstance(iv, dict):
                        lines.append(f"{pad_in}  {ik} {{")
                        for iik, iiv in iv.items():
                            fiiv = _format_value(iiv, indent + 3)
                            if isinstance(iiv, dict):
                                lines.append(f"{pad_in}    {iik} {{")
                                for iiik, iiiv in iiv.items():
                                    fiiiv = _format_value(iiiv, indent + 4)
                                    lines.append(f"{pad_in}      {iiik} = {fiiiv}")
                                lines.append(f"{pad_in}    }}")
                            else:
                                lines.append(f"{pad_in}    {iik} = {fiiv}")
                        lines.append(f"{pad_in}  }}")
                    elif isinstance(iv, list) and iv and isinstance(iv[0], dict):
                        for item in iv:
                            lines.append(f"{pad_in}  {ik} {{")
                            for lk, lv in item.items():
                                flv = _format_value(lv, indent + 3)
                                lines.append(f"{pad_in}    {lk} = {flv}")
                            lines.append(f"{pad_in}  }}")
                    else:
                        lines.append(f"{pad_in}  {ik} = {fv}")
                lines.append(f"{pad_in}}}")
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                for item in v:
                    lines.append(f"{pad_in}{k} {{")
                    for lk, lv in item.items():
                        flv = _format_value(lv, indent + 2)
                        lines.append(f"{pad_in}  {lk} = {flv}")
                    lines.append(f"{pad_in}}}")
            else:
                lines.append(f"{pad_in}{k} = {formatted_v}")
        return "{\n" + "\n".join(lines) + f"\n{pad}}}"

    return f'"{value}"'


def block_to_hcl(block) -> str:
    """
    Convert a single TFBlock to an HCL string.

    TFBlock is imported from nodes.base_node — this function accepts any
    object that has .block_type, .labels, .body, and .comment attributes.

    Example output:
      resource "google_pubsub_topic" "my_topic" {
        name    = "my-topic"
        project = var.project_id
      }
    """
    lines: list[str] = []

    if block.comment:
        for c_line in block.comment.splitlines():
            if c_line.startswith("#"):
                lines.append(c_line)
            else:
                lines.append(f"# {c_line.lstrip('# ')}")

    label_str = " ".join(f'"{lbl}"' for lbl in block.labels)
    lines.append(f"{block.block_type} {label_str} {{")

    for key, value in block.body.items():
        if key.startswith("_"):
            lines.append(f"  {value}")
            continue
        formatted = _format_value(value, indent=1)
        if isinstance(value, dict):
            lines.append(f"  {key} {formatted}")
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                lines.append(f"  {key} {{")
                for lk, lv in item.items():
                    flv = _format_value(lv, 2)
                    lines.append(f"    {lk} = {flv}")
                lines.append("  }")
        else:
            lines.append(f"  {key} = {formatted}")

    lines.append("}")
    return "\n".join(lines)


def blocks_to_hcl(blocks: list) -> str:
    """Join multiple TFBlock objects with blank lines between them."""
    return "\n\n".join(block_to_hcl(b) for b in blocks)