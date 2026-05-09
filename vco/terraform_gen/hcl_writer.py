"""
terraform_gen/hcl_writer.py
============================
Converts TFBlock dataclass objects into properly formatted Terraform HCL.

Rules:
  - type = string / number / bool / map(string) etc  → bare (no quotes)
  - Bare TF references (var.x, local.x, module.x.y)  → no quotes
  - ${...} interpolations                             → quoted
  - true / false / null                               → bare
  - Booleans                                          → true / false
  - Numbers                                           → unquoted
  - Empty dict {}                                     → = {}  (assignment, not block)
  - Non-empty dict                                    → block  key { ... }
  - Keys starting with "dynamic "                     → dynamic block
  - "locals" block_type                               → locals { ... }  (no label quotes)
"""
from __future__ import annotations

import re
from typing import Any


# HCL primitive type keywords — never quoted
_HCL_TYPES = {
    "string", "number", "bool", "any",
    "list(string)", "list(number)", "list(bool)", "list(any)",
    "map(string)", "map(number)", "map(bool)", "map(any)",
    "set(string)", "set(number)", "set(bool)",
    "object({})", "tuple([])",
}


def _is_tf_ref(value: str) -> bool:
    """True → write bare (no quotes)."""
    if not value:
        return False
    # HCL type keywords
    if value in _HCL_TYPES:
        return True
    # HCL keywords
    if value in ("true", "false", "null"):
        return True
    # ${...} interpolation — MUST be quoted
    if value.startswith("${"):
        return False
    # Bare references: var.x  local.x  module.x.y  google_*.*.attr
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
        if not value:
            return "{}"
        lines = []
        for k, v in value.items():
            if k.startswith("_"):
                lines.append(f"{pad_in}{v}")
                continue
            _write_kv(lines, k, v, indent)
        return "{\n" + "\n".join(lines) + f"\n{pad}}}"

    return f'"{value}"'


def _write_kv(lines: list[str], key: str, value: Any, indent: int) -> None:
    """Write one key/value pair into lines[] at the given indent level."""
    pad_in = "  " * (indent + 1)

    # dynamic block:  "dynamic env" or "dynamic vpc_access"
    if key.startswith("dynamic "):
        block_label = key[len("dynamic "):]
        lines.append(f"{pad_in}dynamic \"{block_label}\" {{")
        if isinstance(value, dict):
            inner = indent + 2
            pad2  = "  " * inner
            pad3  = "  " * (inner + 1)
            for ik, iv in value.items():
                if ik == "content":
                    lines.append(f"{pad2}content {{")
                    if isinstance(iv, dict):
                        for ck, cv in iv.items():
                            lines.append(f"{pad3}{ck} = {_format_value(cv, inner + 1)}")
                    lines.append(f"{pad2}}}")
                else:
                    lines.append(f"{pad2}{ik} = {_format_value(iv, inner)}")
        lines.append(f"{pad_in}}}")
        return

    formatted = _format_value(value, indent + 1)

    if isinstance(value, dict) and value:
        # Non-empty dict → block syntax  key { ... }
        lines.append(f"{pad_in}{key} {formatted}")
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        # List of dicts → repeated blocks
        for item in value:
            lines.append(f"{pad_in}{key} {{")
            inner_pad = "  " * (indent + 2)
            for lk, lv in item.items():
                lines.append(f"{inner_pad}{lk} = {_format_value(lv, indent + 2)}")
            lines.append(f"{pad_in}}}")
    else:
        # Assignment
        lines.append(f"{pad_in}{key} = {formatted}")


def block_to_hcl(block) -> str:
    """Convert a single TFBlock to HCL string."""
    lines: list[str] = []

    if block.comment:
        for c_line in block.comment.splitlines():
            lines.append(c_line if c_line.startswith("#") else f"# {c_line.lstrip('# ')}")

    # locals block has no labels and no quotes
    if block.block_type == "locals":
        lines.append("locals {")
        for key, value in block.body.items():
            pad_in = "  "
            if key.startswith("_"):
                lines.append(f"  {value}")
            else:
                lines.append(f"  {key} = {_format_value(value, 1)}")
        lines.append("}")
        return "\n".join(lines)

    # variable block: type value must be bare (string not "string")
    if block.block_type == "variable":
        label_str = " ".join(f'"{lbl}"' for lbl in block.labels)
        lines.append(f"variable {label_str} {{")
        for key, value in block.body.items():
            if key == "type":
                # Always bare for type declarations
                lines.append(f"  type = {value}")
            elif key == "default" and isinstance(value, dict) and not value:
                lines.append("  default = {}")
            elif key.startswith("_"):
                lines.append(f"  {value}")
            else:
                lines.append(f"  {key} = {_format_value(value, 1)}")
        lines.append("}")
        return "\n".join(lines)

    label_str = " ".join(f'"{lbl}"' for lbl in block.labels)
    lines.append(f"{block.block_type} {label_str} {{")

    for key, value in block.body.items():
        if key.startswith("_"):
            lines.append(f"  {value}")
            continue
        _write_kv(lines, key, value, indent=0)

    lines.append("}")
    return "\n".join(lines)


def blocks_to_hcl(blocks: list) -> str:
    return "\n\n".join(block_to_hcl(b) for b in blocks)