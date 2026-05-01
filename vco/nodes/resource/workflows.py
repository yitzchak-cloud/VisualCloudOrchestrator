"""
nodes/workflows.py — Cloud Workflows resource node (fully self-describing).

Changes from previous version
------------------------------
  • Added iam_binding input port (so IamBindingNode can target this workflow).

Topology
--------
  WorkflowNode ──(SERVICE_ACCOUNT)──► ServiceAccountNode   (execution SA)
  WorkflowNode ──(HTTP_TARGET)──────► CloudRunNode          (step targets)
  WorkflowNode ──(STORAGE)──────────► GcsBucketNode         (env: GCS_BUCKET_<NAME>)
  WorkflowNode ──(TASK_QUEUE)───────► CloudTasksQueueNode   (env: CLOUD_TASKS_QUEUE_<NAME>)
  WorkflowNode ──(STORAGE)──────────► FirestoreNode          (env: FIRESTORE_DATABASE_<NAME>)

  FirestoreNode    ──(STORAGE)──────► WorkflowNode  (visual step reference)
  CloudVisionNode  ──(HTTP_TARGET)──► WorkflowNode  (visual step reference)
  CloudFunctionsNode──(HTTP_TARGET)─► WorkflowNode  (visual step reference)

  IamBindingNode   ──(IAM_BINDING)──► WorkflowNode  ← NEW
    (pulumi_gcp has no WorkflowIamMember — falls back to project-level IAMMember
     for roles like roles/workflows.invoker)

Exports
-------
  workflow_id   — fully-qualified workflow resource id
  workflow_name — short name (used by trigger / scheduler)
"""
from __future__ import annotations

import logging
import re
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

    Connect to CloudRunNode(s)         → sequential HTTP call steps (auto-YAML).
    Connect to ServiceAccountNode      → run under that identity.
    Connect to GcsBucketNode           → injects GCS_BUCKET_* env var into workflow.
    Connect to CloudTasksQueueNode     → injects CLOUD_TASKS_QUEUE_* env var.
    Connect to FirestoreNode           → injects FIRESTORE_DATABASE_* env var (visual).
    Connect to CloudVisionNode         → injects CLOUD_VISION_URL env var (visual).
    Connect to CloudFunctionsNode      → injects CLOUD_FUNCTIONS_URL_* env var (visual).
    Connect IamBindingNode → this      → grants roles on this workflow (project-level fallback).
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
            "type": "yaml", "default": "",
            "placeholder": "main:\n  steps:\n  - ...",
        },
        {
            "key": "http_path", "label": "Default HTTP path for wired services",
            "type": "text", "default": "/", "placeholder": "/run",
        },
    ]

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT,   required=False),
        Port("firestore",       PortType.STORAGE,            required=False, multi=True, multi_in=True),
        Port("visual",          PortType.VISUAL_CONNECTION,  multi_in=True),
        Port("iam_binding",     PortType.IAM_BINDING,        required=False, multi=True, multi_in=True),  # NEW
    ]
    outputs: ClassVar = [
        Port("calls",      PortType.HTTP_TARGET,       multi=True),   # → CloudRunNode / visual nodes
        Port("writes_to",  PortType.STORAGE,           multi=True),   # → GcsBucketNode / FirestoreNode
        Port("task_queue", PortType.TASK_QUEUE,        multi=True),   # → CloudTasksQueueNode
        Port("visual",     PortType.VISUAL_CONNECTION, multi=True),   # → visual nodes
    ]

    node_color:  ClassVar = "#c084fc"
    icon:        ClassVar = "workflows"
    category:    ClassVar = "Integration_Services"
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

        # STORAGE output → GcsBucketNode
        if tgt_type == "GcsBucketNode":
            ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
            ctx[self.node_id].setdefault("bucket_ids", []).append(tgt_id)
            return True

        # STORAGE output → FirestoreNode (visual — env var injection)
        if tgt_type == "FirestoreNode":
            ctx[self.node_id].setdefault("firestore_ids", []).append(tgt_id)
            return True

        # TASK_QUEUE output → CloudTasksQueueNode (visual — env var)
        if tgt_type == "CloudTasksQueueNode":
            ctx[self.node_id].setdefault("task_queue_ids", []).append(tgt_id)
            return True

        # Visual: CloudVisionNode / CloudFunctionsNode / ExternalApiNode
        if tgt_type in ("CloudVisionNode", "CloudFunctionsNode", "ExternalApiNode"):
            ctx[self.node_id].setdefault("visual_api_ids", []).append(tgt_id)
            return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        deps  = list(ctx.get("target_run_ids",  []))
        deps += list(ctx.get("bucket_ids",       []))
        deps += list(ctx.get("task_queue_ids",   []))
        deps += list(ctx.get("firestore_ids",    []))
        deps += list(ctx.get("visual_api_ids",   []))
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

        target_run_ids  = ctx.get("target_run_ids",  [])
        bucket_ids      = ctx.get("bucket_ids",      [])
        task_queue_ids  = ctx.get("task_queue_ids",  [])
        firestore_ids   = ctx.get("firestore_ids",   [])
        visual_api_ids  = ctx.get("visual_api_ids",  [])

        def program() -> None:
            wf_name     = props.get("name") or _resource_name(node_dict)
            wf_region   = props.get("region", region)
            http_path   = props.get("http_path", "/")
            source_yaml = (props.get("source_yaml") or "").strip()

            # ── Auto-generate YAML from wired Cloud Run nodes ──────────────
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

            # ── Env vars: GCS buckets ──────────────────────────────────────
            bucket_env_vars = {
                "GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()):
                    deployed_outputs.get(bid, {}).get("name", "")
                for bid in bucket_ids
            }

            # ── Env vars: Cloud Tasks queues ───────────────────────────────
            queue_env_vars = {
                "CLOUD_TASKS_QUEUE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, qid).upper()):
                    deployed_outputs.get(qid, {}).get("queue_name", "")
                for qid in task_queue_ids
            }

            # ── Env vars: Firestore databases ──────────────────────────────
            firestore_env_vars = {
                "FIRESTORE_DATABASE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, fid).upper()):
                    deployed_outputs.get(fid, {}).get("database_id", "(default)")
                for fid in firestore_ids
            }

            # ── Env vars: Visual API nodes (Vision, Functions, External) ───
            visual_env_vars = {}
            for vid in visual_api_ids:
                out  = deployed_outputs.get(vid, {})
                url  = out.get("url",  "")
                name = out.get("name", _node_name(all_nodes, vid))
                key  = re.sub(r"[^A-Z0-9]", "_", name.upper())
                if url:
                    visual_env_vars[f"API_URL_{key}"] = url

            all_env_vars = {
                **bucket_env_vars,
                **queue_env_vars,
                **firestore_env_vars,
                **visual_env_vars,
            }

            wf = gcp.workflows.Workflow(
                self.node_id,
                name=wf_name,
                region=wf_region,
                project=project,
                service_account=sa_email or None,
                source_contents=source_yaml,
                labels={
                    k.lower().replace("_", "-")[:63]: v[:63]
                    for k, v in list(all_env_vars.items())[:64]
                } if all_env_vars else None,
            )

            pulumi.export("workflow_name", wf.name)
            pulumi.export("workflow_id",   wf.id)
            for k, v in all_env_vars.items():
                pulumi.export(f"env_{k}", v)

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