"""
pulumi_synth.py  — backwards-compatibility shim
================================================
This file used to contain all deployment logic.
Everything has been moved to the  deploy/  package.

Keeping this file means existing imports like:
    from pulumi_synth import synthesize_and_deploy, read_actual_state
continue to work without any changes.

>>> Do not add new logic here. <<<
"""
from deploy import (  # noqa: F401  (re-export for callers)
    build_dag,
    read_actual_state,
    resolve_graph,
    synthesize_and_deploy,
    synthesize_only,
)
