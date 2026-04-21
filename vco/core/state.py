"""
core/state.py
=============
Central definition of all filesystem paths used by the app.
Import from here — never hardcode paths in routes.
"""
from __future__ import annotations

from pathlib import Path

# Desired graph state (YAML snapshot of the canvas)
STATE_FILE: Path = Path("state/desired.yaml")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# Root directory for per-node Pulumi stacks
STACK_DIR: Path = Path("state/pulumi_stack")
STACK_DIR.mkdir(parents=True, exist_ok=True)
