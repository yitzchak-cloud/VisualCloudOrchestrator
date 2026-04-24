"""
nodes/workflows.py — Cloud Workflows resource node (fully self-describing).

Topology
--------
  WorkflowNode ──(SERVICE_ACCOUNT)──► ServiceAccountNode  (execution SA)
  WorkflowNode ──(HTTP_TARGET)──────► CloudRunNode         (step targets)

Cloud Workflows is an HTTP orchestrator.  Each wired CloudRunNode becomes an
available step-target: the workflow YAML is auto-generated with an http.post
step for every wired service, so you get a working skeleton immediately.

You can also paste your own YAML into the `source_yaml` parameter — if that
field is non-empty it takes precedence over the auto-generated YAML.

Exports
-------
  workflow_id   — fully-qualified workflow resource id
  workflow_name — short name (used by trigger / scheduler)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# Minimal YAML skeleton for a single HTTP step
_STEP_YAML_TMPL = """\
  - {step_name}:
      call: http.post
      args:
        url: {url}
        auth:
          type: OIDC
      result: {step_name}_result
"""

_WORKFLOW_YAML_TMPL = """\
main:
  steps:
{steps}
  - returnResult:
      return: "done"
"""


def _build_yaml(step_urls: list[tuple[str, str]]) -> str:
    """Build a simple sequential workflow YAML from (step_name, url) pairs."""
    steps = "".join(
        _STEP_YAML_TMPL.format(step_name=name, url=url)
        for name, url in step_urls
    )
    return _WORKFLOW_YAML_TMPL.format(steps=steps)


@dataclass
class WorkflowNode(GCPNode):
    """
    Cloud Workflows — HTTP services orchestrator.

    Connect to CloudRunNode(s) to generate a sequential call workflow.
    Connect to ServiceAccountNode to run the workflow under that identity.
    """

    params_schema: ClassVar = [
        {
            "key": "name", "label": "Workflow Name",
            "type": "text", "default": "", "placeholder": "my-workflow",
        },
        {
            "key": "region", "label": "Region",
            "type": "select",
            "options": ["me-west1", "us-central1", "us-east1", "europe-west1"],
            "default": "me-west1",
        },
        {
            "key": "source_yaml", "label": "Custom YAML (overrides auto-generated)",
            "type": "textarea", "default": "",
            "placeholder": "main:\n  steps:\n  - ...",
        },
        {
            "key": "http_path", "label": "Default HTTP path for wired services",
            "type": "text", "default": "/", "placeholder": "/run",
        },
    ]

    inputs:  ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("calls", PortType.HTTP_TARGET, multi=True),
    ]

    node_color:  ClassVar = "#c084fc"
    icon:        ClassVar = "workflows"
    category:    ClassVar = "Orchestration"
    description: ClassVar = "HTTP services orchestration"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id != self.node_id:
            return False
        if tgt_type == "CloudRunNode":
            ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps  = list(ctx.get("target_run_ids", []))
        sa_id = ctx.get("service_account_id")
        if sa_id:
            deps.append(sa_id)
        return deps

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "")

        target_run_ids = ctx.get("target_run_ids", [])

        def program() -> None:
            wf_name     = props.get("name") or _resource_name(node_dict)
            wf_region   = props.get("region", region)
            http_path   = props.get("http_path", "/")
            source_yaml = (props.get("source_yaml") or "").strip()

            # Auto-generate YAML if user didn't supply one
            if not source_yaml:
                step_urls: list[tuple[str, str]] = []
                for run_id in target_run_ids:
                    uri = deployed_outputs.get(run_id, {}).get("uri", "")
                    if uri:
                        step_name = re.sub(
                            r"[^a-z0-9_]", "_",
                            _node_name(all_nodes, run_id).lower()
                        )
                        step_urls.append((step_name, uri.rstrip("/") + http_path))

                source_yaml = _build_yaml(step_urls) if step_urls else (
                    "main:\n  steps:\n  - returnResult:\n      return: \"no targets wired\"\n"
                )

            wf = gcp.workflows.Workflow(
                self.node_id,
                name=wf_name,
                region=wf_region,
                project=project,
                service_account=sa_email or None,
                source_contents=source_yaml,
            )

            pulumi.export("workflow_name", wf.name)
            pulumi.export("workflow_id",   wf.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"name": pulumi_outputs.get("workflow_name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("workflow_name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="workflows.googleapis.com/Workflow"'
                f' AND resource.labels.workflow_id="{name}"'
            ),
            project=project,
        )


# missing import used in program() closure
import re  # noqa: E402