"""
core/state.py
=============
Central definition of all filesystem paths used by the app.
Every path is now scoped to a *namespace* so different canvases are
fully isolated on disk.

Namespace rules:
  - Name may only contain [a-zA-Z0-9_-] (validated on creation).
  - Default namespace is "default".
  - All data for namespace "foo" lives under  state/namespaces/foo/

Directory layout per namespace:
  state/namespaces/<ns>/
      desired.yaml          ← canvas snapshot
      pulumi_stack/         ← per-node Pulumi stacks
      logs/                 ← deploy.jsonl + node_events.json

The module also keeps the legacy STATE_FILE / STACK_DIR constants
pointing at the "default" namespace so existing code that imports
them directly continues to work unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

# ── Root ──────────────────────────────────────────────────────────────────────
_NS_ROOT = Path("state/namespaces")
_NS_ROOT.mkdir(parents=True, exist_ok=True)

# Namespace name validation pattern
_VALID_NS = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_namespace(name: str) -> bool:
    return bool(_VALID_NS.match(name))


# ── Per-namespace path helpers ────────────────────────────────────────────────

def ns_dir(namespace: str = "default") -> Path:
    """Root directory for a namespace. Created on first access."""
    d = _NS_ROOT / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file(namespace: str = "default") -> Path:
    """Path to desired.yaml for a namespace."""
    return ns_dir(namespace) / "desired.yaml"


def stack_dir(namespace: str = "default") -> Path:
    """Path to the Pulumi stack directory for a namespace."""
    d = ns_dir(namespace) / "pulumi_stack"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir(namespace: str = "default") -> Path:
    """Path to the logs directory for a namespace."""
    d = ns_dir(namespace) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Namespace management ──────────────────────────────────────────────────────

def list_namespaces() -> list[str]:
    """Return sorted list of existing namespace names."""
    if not _NS_ROOT.exists():
        return ["default"]
    names = [d.name for d in _NS_ROOT.iterdir() if d.is_dir()]
    if not names:
        return ["default"]
    return sorted(names)


def create_namespace(name: str) -> bool:
    """
    Create a new namespace directory.
    Returns True on success, False if name is invalid or already exists.
    """
    if not validate_namespace(name):
        return False
    target = _NS_ROOT / name
    if target.exists():
        return False
    ns_dir(name)          # creates + sub-dirs
    stack_dir(name)
    logs_dir(name)
    return True


def delete_namespace(name: str) -> bool:
    """
    Delete a namespace and ALL its data (graph, stacks, logs).
    Returns False if namespace is "default" or does not exist.
    """
    if name == "default":
        return False
    target = _NS_ROOT / name
    if not target.exists():
        return False
    import shutil
    shutil.rmtree(target)
    return True


# ── Legacy aliases — point at "default" namespace ─────────────────────────────
# Existing imports like  `from core.state import STATE_FILE, STACK_DIR`
# continue to work without modification.

STATE_FILE = state_file("default")
STACK_DIR  = stack_dir("default")