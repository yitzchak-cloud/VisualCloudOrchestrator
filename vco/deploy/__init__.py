"""
deploy/__init__.py
==================
Public API for the deploy package.
Import from here, not from individual submodules.

Also re-exports the names that the old  pulumi_synth.py  exposed at the top
level, so any code that still does  `from pulumi_synth import ...`  can be
migrated gradually.
"""
from deploy.graph_resolver import build_dag, resolve_graph
from deploy.orchestrator import synthesize_and_deploy, synthesize_only
from deploy.state_reader import read_actual_state

__all__ = [
    "resolve_graph",
    "build_dag",
    "synthesize_and_deploy",
    "synthesize_only",
    "read_actual_state",
]
