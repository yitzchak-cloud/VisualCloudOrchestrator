"""
nodes/cloud_functions.py — Cloud Functions (Gen 2) resource node (fully self-describing).

Purpose
-------
Deploys a Cloud Functions Gen 2 HTTP-triggered function and wires it into the
VCO architecture.

Cloud Functions Gen 2 is built on Cloud Run — under the hood each function is
a Cloud Run service.  However, it has a distinct deployment model (source-based,
not image-based) and a distinct IAM surface (roles/cloudfunctions.invoker).

Topology
--------
  WorkflowNode     ──(HTTP_TARGET)──► CloudFunctionsNode
  CloudRunNode     ──(HTTP_TARGET)──► CloudFunctionsNode   (CR calls the function)
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudFunctionsNode
  GcsBucketNode    ──(STORAGE)──────► CloudFunctionsNode   (env: GCS_BUCKET_<NAME>)
  IamBindingNode   ──(IAM_BINDING)──► CloudFunctionsNode   (invoker grants)

  CloudFunctionsNode ──(HTTP_TARGET)──► WorkflowNode / CloudRunNode
    (the function's URL is exported so callers can call it back)

  CloudFunctionsNode ──(STORAGE)──────► GcsBucketNode
    (function writes to a bucket)

Equivalent gcloud deployment
-----------------------------
  gcloud functions deploy ${EXTRACT_FUNCTION_NAME} \\
    --gen2 \\
    --source . \\
    --runtime=nodejs20 \\
    --entry-point=extract_image_metadata \\
    --trigger-http \\
    --no-allow-unauthenticated

IAM binding (wired SA → this function):
  gcloud functions add-iam-policy-binding ${FUNCTION_NAME} \\
    --member="serviceAccount:${SA_EMAIL}" \\
    --role="roles/cloudfunctions.invoker"

Exports
-------
  url       — the function's HTTPS trigger URL
  name      — the deployed function name
  id        — full resource id
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

_RUNTIMES = [
    "nodejs20", "nodejs18", "python312", "python311", "python310",
    "go122", "go121", "java21", "java17", "dotnet8", "ruby33",
]


@dataclass
class CloudFunctionsNode(GCPNode):
    """
    Cloud Functions Gen 2 — HTTP-triggered serverless function.

    Source is uploaded from a GCS bucket (source_bucket / source_object props).
    If you prefer, set source_bucket to your deployment bucket and source_object
    to the zip path; or leave both empty to use a placeholder "hello world"
    inline source for initial scaffolding.

    Connect FROM WorkflowNode / CloudRunNode to represent a function call step.
    The function URL is exported and injected as:
      API_URL_<FUNCTION_NAME>  into any connected WorkflowNode or CloudRunNode.
    """

    params_schema: ClassVar = [
        {
            "key":         "name",
            "label":       "Function Name",
            "type":        "text",
            "default":     "",
            "placeholder": "extract-image-metadata",
        },
        {
            "key":         "entry_point",
            "label":       "Entry Point",
            "type":        "text",
            "default":     "",
            "placeholder": "extract_image_metadata",
        },
        {
            "key":         "runtime",
            "label":       "Runtime",
            "type":        "select",
            "options":     _RUNTIMES,
            "default":     "nodejs20",
        },
        {
            "key":         "region",
            "label":       "Region",
            "type":        "select",
            "options":     ["me-west1", "us-central1", "us-east1", "europe-west1"],
            "default":     "me-west1",
        },
        {
            "key":         "source_bucket",
            "label":       "Source Bucket (GCS)",
            "type":        "text",
            "default":     "",
            "placeholder": "my-deployment-bucket",
        },
        {
            "key":         "source_object",
            "label":       "Source Object (zip path in bucket)",
            "type":        "text",
            "default":     "",
            "placeholder": "functions/extract-metadata.zip",
        },
        {
            "key":         "memory",
            "label":       "Memory",
            "type":        "select",
            "options":     ["128Mi", "256Mi", "512Mi", "1Gi", "2Gi", "4Gi"],
            "default":     "256Mi",
        },
        {
            "key":         "timeout",
            "label":       "Timeout (seconds)",
            "type":        "number",
            "default":     60,
        },
        {
            "key":         "max_instances",
            "label":       "Max Instances",
            "type":        "number",
            "default":     10,
        },
        {
            "key":         "allow_unauthenticated",
            "label":       "Allow Unauthenticated",
            "type":        "checkbox",
            "default":     False,
        },
        {
            "key":         "function_url",
            "label":       "Function URL (set after deploy)",
            "type":        "text",
            "default":     "",
            "placeholder": "https://REGION-PROJECT.cloudfunctions.net/FUNCTION",
        },
    ]

    url_field: ClassVar = "function_url"

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
        Port("callers",         PortType.HTTP_TARGET,      required=False, multi=True, multi_in=True),
        Port("bucket_in",       PortType.STORAGE,          required=False, multi=True, multi_in=True),
        Port("iam_binding",     PortType.IAM_BINDING,      required=False, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("http_out",  PortType.HTTP_TARGET, multi=True),   # → WorkflowNode / CloudRunNode (callers)
        Port("writes_to", PortType.STORAGE,     multi=True),   # → GcsBucketNode
    ]

    node_color:  ClassVar = "#f59e0b"
    icon:        ClassVar = "cloudFunctions"
    category:    ClassVar = "Compute"
    description: ClassVar = "Cloud Functions Gen 2 — HTTP-triggered serverless function"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # WorkflowNode / CloudRunNode → this function (caller registers it)
        if tgt_id == self.node_id:
            if src_type in ("WorkflowNode", "CloudRunNode"):
                ctx[src_id].setdefault("visual_api_ids", []).append(self.node_id)
                return True
            if src_type == "GcsBucketNode":
                # Bucket injects env var into function
                ctx[self.node_id].setdefault("bucket_ids", []).append(src_id)
                return True

        # This function → GcsBucketNode (function writes to bucket)
        if src_id == self.node_id and tgt_type == "GcsBucketNode":
            ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
            ctx[self.node_id].setdefault("bucket_ids", []).append(tgt_id)
            return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = list(ctx.get("bucket_ids", []))
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(
        self,
        ctx:              dict[str, Any],
        project:          str,
        region:           str,
        all_nodes:        list[dict],
        deployed_outputs: dict[str, dict],
    ) -> Callable[[], None] | None:

        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_email = deployed_outputs.get(ctx.get("service_account_id", ""), {}).get("email", "")

        bucket_ids = ctx.get("bucket_ids", [])

        def program() -> None:
            fn_name       = props.get("name") or _resource_name(node_dict)
            entry_point   = props.get("entry_point", fn_name.replace("-", "_"))
            runtime       = props.get("runtime", "nodejs20")
            fn_region     = props.get("region", region)
            memory        = props.get("memory", "256Mi")
            timeout       = int(props.get("timeout", 60))
            max_instances = int(props.get("max_instances", 10))
            allow_unauth  = props.get("allow_unauthenticated", False)
            src_bucket    = props.get("source_bucket", "")
            src_object    = props.get("source_object", "")

            # ── Memory: convert Mi/Gi string → integer MB ─────────────────
            # pulumi_gcp Gen1 Function uses available_memory_mb (int).
            _mem_map = {
                "128Mi": 128, "256Mi": 256, "512Mi": 512,
                "1Gi": 1024, "2Gi": 2048, "4Gi": 4096,
            }
            available_memory_mb = _mem_map.get(memory, 256)

            # ── Bucket env vars ───────────────────────────────────────────
            # environment_variables is a plain dict[str, str] in Gen1.
            bucket_env_vars: dict[str, str] = {
                "GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()):
                    deployed_outputs.get(bid, {}).get("name", "")
                for bid in bucket_ids
            }

            # ── Source ────────────────────────────────────────────────────
            # Gen1 API: source_archive_bucket / source_archive_object for GCS zips,
            # or source_repository (FunctionSourceRepositoryArgs) for CSR.
            # If neither is configured, use a CSR placeholder so the resource
            # can be created without a real zip (replace before production).
            source_archive_bucket: str | None = None
            source_archive_object: str | None = None
            source_repository = None

            if src_bucket and src_object:
                source_archive_bucket = src_bucket
                source_archive_object = src_object
            else:
                # Placeholder: point at a Cloud Source Repository branch.
                # Replace with a real GCS zip before production use.
                source_repository = gcp.cloudfunctions.FunctionSourceRepositoryArgs(
                    url=(
                        f"https://source.developers.google.com"
                        f"/projects/{project}/repos/{fn_name}/moveable-aliases/main/paths/"
                    ),
                )

            fn = gcp.cloudfunctions.Function(
                self.node_id,
                name=fn_name,
                region=fn_region,
                project=project,
                runtime=runtime,
                entry_point=entry_point,
                trigger_http=True,
                available_memory_mb=available_memory_mb,
                timeout=timeout,
                max_instances=max_instances,
                service_account_email=sa_email or None,
                environment_variables=bucket_env_vars if bucket_env_vars else None,
                source_archive_bucket=source_archive_bucket,
                source_archive_object=source_archive_object,
                source_repository=source_repository,
            )

            # ── IAM: allow unauthenticated invoker ────────────────────────
            # Equivalent:
            #   gcloud functions add-iam-policy-binding ${FUNCTION_NAME} \
            #     --region=${REGION} \
            #     --member="allUsers" \
            #     --role="roles/cloudfunctions.invoker"
            if allow_unauth:
                gcp.cloudfunctions.FunctionIamMember(
                    f"{self.node_id}-public",
                    project=project,
                    region=fn_region,
                    cloud_function=fn.name,
                    role="roles/cloudfunctions.invoker",
                    member="allUsers",
                )

            # https_trigger_url is the Gen1 output attribute for the invocation URL.
            pulumi.export("url",  fn.https_trigger_url)
            pulumi.export("name", fn.name)
            pulumi.export("id",   fn.id)

        return program

    # ------------------------------------------------------------------
    # Post-deploy
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"function_url": pulumi_outputs.get("url", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="cloud_function"'
                f' AND resource.labels.function_name="{name}"'
            ),
            project=project,
        )