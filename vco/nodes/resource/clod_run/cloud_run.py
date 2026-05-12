"""
nodes/resource/cloud_run/cloud_run.py
──────────────────────────────────────────────────────────────────────────────
CloudRunNode — full Cloud Run v2 service node.

Supports both Pulumi and Terraform backends.

What changed vs previous version
─────────────────────────────────
* All params_schema removed from class fields → loaded from cloud_run_params.yaml.
* cpu, memory, port, concurrency, timeout_seconds, execution_environment,
  startup_cpu_boost, vpc_egress, labels, annotations all wired through to
  both pulumi_program() and terraform_blocks().
* Terraform main.tf now sets resources{limits{}}, ports{}, concurrency,
  timeout, execution_environment, labels, annotations.
* terraform_call_vars() updated to match new variables.tf.
* Pulumi IamMember uses correct cloudrunv2 API (not cloudrun v1).
* pulumi.export adds "service_url" alias for live_outputs.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import (
    GCPNode, LogSource, Port, TFBlock, TFResult,
    _resource_name, _tf_name, _node_label, _node_name, _node_by_id,
)
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# ── helpers ───────────────────────────────────────────────────────────────────

def _env_key(label: str) -> str:
    """Convert an arbitrary label into a valid SCREAMING_SNAKE env-var suffix."""
    return re.sub(r"[^A-Z0-9]", "_", label.upper())


def _parse_json_prop(raw: str) -> dict:
    """Safely parse a JSON string prop; return {} on any error."""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── node ──────────────────────────────────────────────────────────────────────

@dataclass
class CloudRunNode(GCPNode):
    """Serverless container runtime — Google Cloud Run v2."""

    # params loaded from cloud_run_params.yaml automatically by base_node
    # (file must sit alongside this module as cloud_run_params.yaml)

    url_field:   ClassVar = "service_url"
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloudRun"
    category:    ClassVar = "Compute"
    description: ClassVar = "Serverless container runtime"

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
        Port("subnet",          PortType.NETWORK,          required=False),
        Port("http_callers",    PortType.HTTP_TARGET,      required=False, multi=True, multi_in=True),
        Port("task_queue",      PortType.TASK_QUEUE,       required=False, multi=True, multi_in=True),
        Port("secret",          PortType.SECRET,           required=False, multi=True, multi_in=True),
        Port("MESSAGE",         PortType.MESSAGE,          required=False, multi=True, multi_in=True),
        Port("storage",         PortType.STORAGE,          required=False, multi=True, multi_in=True),
        Port("iam_binding",     PortType.IAM_BINDING,      required=False, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to", PortType.TOPIC,   multi=True),
        Port("writes_to",    PortType.STORAGE, multi=True),
    ]

    # ──────────────────────────────────────────────────────────────────────────
    # Edge wiring
    # ──────────────────────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # CR is the SOURCE
        if src_id == self.node_id and src_type == "CloudRunNode":
            if tgt_type == "PubsubTopicNode":
                ctx[self.node_id].setdefault("publishes_to_topics", []).append(tgt_id)
                return True
            if tgt_type == "GcsBucketNode":
                # GcsBucketNode.resolve_edges sets writer_ids on the bucket side.
                # No ctx write needed here to avoid double-counting.
                return True
            if tgt_type == "FirestoreNode":
                ctx[self.node_id].setdefault("firestore_ids", []).append(tgt_id)
                return True

        # CR is the TARGET
        if tgt_id == self.node_id:
            if src_type == "FirestoreNode":
                ctx[self.node_id].setdefault("firestore_ids", []).append(src_id)
                return True
            if src_type in ("CloudVisionNode", "CloudFunctionsNode", "ExternalApiNode"):
                ctx[self.node_id].setdefault("visual_api_ids", []).append(src_id)
                return True

        return False

    # ──────────────────────────────────────────────────────────────────────────
    # DAG dependencies
    # ──────────────────────────────────────────────────────────────────────────

    def dag_deps(self, ctx) -> list[str]:
        """
        Only nodes whose DEPLOYED OUTPUT is needed at Pulumi build time.
        Bucket names are taken from graph props (no deploy dep).
        Firestore database_id defaults to '(default)' (no deploy dep).
        """
        deps = list(ctx.get("publishes_to_topics", []))
        deps += ctx.get("task_queue_ids",  [])
        deps += ctx.get("visual_api_ids",  [])
        if ctx.get("subnetwork_id"):
            deps.append(ctx["subnetwork_id"])
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ──────────────────────────────────────────────────────────────────────────
    # Pulumi program
    # ──────────────────────────────────────────────────────────────────────────

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        # ── VPC ───────────────────────────────────────────────────────────────
        subnet_id       = ctx.get("subnetwork_id", "")
        subnet_outputs  = deployed_outputs.get(subnet_id, {})
        network_path    = subnet_outputs.get("network_path")    or props.get("vpc_network",    "")
        subnetwork_path = subnet_outputs.get("subnetwork_path") or props.get("vpc_subnetwork", "")

        # ── Service Account ───────────────────────────────────────────────────
        sa_email = deployed_outputs.get(ctx.get("service_account_id", ""), {}).get("email", "")

        # ── Environment variables from connected nodes ─────────────────────────
        topic_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name  = "PUBSUB_TOPIC_" + _env_key(_node_name(all_nodes, tid)),
                value = deployed_outputs.get(tid, {}).get("name", ""),
            )
            for tid in ctx.get("publishes_to_topics", [])
        ]
        sub_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name  = "PUBSUB_SUBSCRIPTION_" + _env_key(_node_name(all_nodes, sid)),
                value = _resource_name(next((n for n in all_nodes if n["id"] == sid), {})),
            )
            for sid in ctx.get("receives_from_subs", [])
        ]
        bucket_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name  = "GCS_BUCKET_" + _env_key(_node_name(all_nodes, bid)),
                value = _resource_name(_node_by_id(all_nodes, bid)),
            )
            for bid in ctx.get("bucket_ids", [])
        ]
        queue_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name  = "CLOUD_TASKS_QUEUE_" + _env_key(_node_name(all_nodes, qid)),
                value = deployed_outputs.get(qid, {}).get("queue_name", ""),
            )
            for qid in ctx.get("task_queue_ids", [])
        ]
        firestore_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name  = "FIRESTORE_DATABASE_" + _env_key(_node_name(all_nodes, fid)),
                value = deployed_outputs.get(fid, {}).get("database_id", "(default)"),
            )
            for fid in ctx.get("firestore_ids", [])
        ]
        visual_api_envs = []
        for vid in ctx.get("visual_api_ids", []):
            out   = deployed_outputs.get(vid, {})
            url   = out.get("url", "")
            vname = out.get("name", _node_name(all_nodes, vid))
            if url:
                visual_api_envs.append(
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                        name=f"API_URL_{_env_key(vname)}", value=url,
                    )
                )

        all_envs = (
            topic_envs + sub_envs + bucket_envs + queue_envs
            + firestore_envs + visual_api_envs
        )

        # ── Capture props for closure ─────────────────────────────────────────
        image               = props.get("image", "gcr.io/cloudrun/hello")
        port                = int(props.get("port", 8080))
        cpu                 = str(props.get("cpu", "1"))
        memory              = str(props.get("memory", "512Mi"))
        concurrency         = int(props.get("concurrency", 80))
        timeout_seconds     = int(props.get("timeout_seconds", 300))
        min_instances       = int(props.get("min_instances", 0))
        max_instances       = int(props.get("max_instances", 10))
        ingress             = props.get("ingress", "INGRESS_TRAFFIC_INTERNAL_ONLY")
        allow_unauth        = bool(props.get("allow_unauthenticated", False))
        exec_env            = props.get("execution_environment", "EXECUTION_ENVIRONMENT_GEN2")
        startup_cpu_boost   = bool(props.get("startup_cpu_boost", False))
        vpc_egress          = props.get("vpc_egress", "PRIVATE_RANGES_ONLY")
        labels              = _parse_json_prop(props.get("labels", ""))
        annotations         = _parse_json_prop(props.get("annotations", ""))

        def program() -> None:
            # VPC access
            vpc_access = None
            if network_path and subnetwork_path:
                vpc_access = gcp.cloudrunv2.ServiceTemplateVpcAccessArgs(
                    egress=vpc_egress,
                    network_interfaces=[
                        gcp.cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=network_path,
                            subnetwork=subnetwork_path,
                        )
                    ],
                )

            svc = gcp.cloudrunv2.Service(
                self.node_id,
                name                = _resource_name(node_dict),
                location            = props.get("region", region),
                project             = project,
                deletion_protection = False,
                ingress             = ingress,
                labels              = labels or None,
                annotations         = annotations or None,
                template=gcp.cloudrunv2.ServiceTemplateArgs(
                    service_account       = sa_email or None,
                    execution_environment = exec_env,
                    max_instance_request_concurrency = concurrency,
                    timeout               = f"{timeout_seconds}s",
                    scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
                        min_instance_count = min_instances,
                        max_instance_count = max_instances,
                    ),
                    vpc_access = vpc_access,
                    containers=[
                        gcp.cloudrunv2.ServiceTemplateContainerArgs(
                            image = image,
                            ports = [
                                gcp.cloudrunv2.ServiceTemplateContainerPortArgs(
                                    container_port=port,
                                )
                            ],
                            resources=gcp.cloudrunv2.ServiceTemplateContainerResourcesArgs(
                                limits={
                                    "cpu":    cpu,
                                    "memory": memory,
                                },
                                startup_cpu_boost=startup_cpu_boost,
                            ),
                            envs=all_envs or None,
                        )
                    ],
                ),
            )

            if allow_unauth:
                gcp.cloudrunv2.ServiceIamMember(
                    f"{self.node_id}-public",
                    project  = project,
                    location = props.get("region", region),
                    name     = svc.name,
                    role     = "roles/run.invoker",
                    member   = "allUsers",
                )

            pulumi.export("uri",         svc.uri)
            pulumi.export("name",        svc.name)
            pulumi.export("id",          svc.id)
            pulumi.export("service_url", svc.uri)   # alias used by live_outputs

        return program

    # ──────────────────────────────────────────────────────────────────────────
    # Terraform — inline blocks
    # ──────────────────────────────────────────────────────────────────────────

    def terraform_blocks(self, ctx, project, region, all_nodes) -> TFResult:
        result    = TFResult()
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        name      = _resource_name(node_dict)
        tf_id     = _tf_name(node_dict)
        r         = props.get("region", region)

        # ── VPC block ─────────────────────────────────────────────────────────
        vpc_block: dict = {}
        subnet_id = ctx.get("subnetwork_id", "")
        egress    = props.get("vpc_egress", "PRIVATE_RANGES_ONLY")
        if subnet_id:
            sn_tf = _tf_name(_node_by_id(all_nodes, subnet_id))
            vpc_block = {
                "egress": egress,
                "network_interfaces": {
                    "network":    f"${{google_compute_subnetwork.{sn_tf}.network}}",
                    "subnetwork": f"${{google_compute_subnetwork.{sn_tf}.self_link}}",
                },
            }
        elif props.get("vpc_network") and props.get("vpc_subnetwork"):
            vpc_block = {
                "egress": egress,
                "network_interfaces": {
                    "network":    props["vpc_network"],
                    "subnetwork": props["vpc_subnetwork"],
                },
            }

        # ── Service Account ───────────────────────────────────────────────────
        sa_email = ""
        sa_id    = ctx.get("service_account_id", "")
        if sa_id:
            sa_node = _node_by_id(all_nodes, sa_id)
            sa_email = (
                f"${{google_service_account.{_tf_name(sa_node)}.email}}"
                if sa_node.get("props", {}).get("create_sa", True)
                else sa_node.get("props", {}).get("email", "")
            )

        # ── Env vars from connected nodes ─────────────────────────────────────
        env_list: list[dict] = []
        for tid in ctx.get("publishes_to_topics", []):
            t = _node_by_id(all_nodes, tid)
            env_list.append({
                "name":  f"PUBSUB_TOPIC_{_env_key(_resource_name(t))}",
                "value": f"${{google_pubsub_topic.{_tf_name(t)}.name}}",
            })
        for bid in ctx.get("bucket_ids", []):
            b = _node_by_id(all_nodes, bid)
            env_list.append({
                "name":  f"GCS_BUCKET_{_env_key(_resource_name(b))}",
                "value": f"${{google_storage_bucket.{_tf_name(b)}.name}}",
            })
        for qid in ctx.get("task_queue_ids", []):
            q = _node_by_id(all_nodes, qid)
            env_list.append({
                "name":  f"CLOUD_TASKS_QUEUE_{_env_key(_resource_name(q))}",
                "value": f"${{google_cloud_tasks_queue.{_tf_name(q)}.name}}",
            })
        for fid in ctx.get("firestore_ids", []):
            fn = _node_by_id(all_nodes, fid)
            env_list.append({
                "name":  f"FIRESTORE_DATABASE_{_env_key(_resource_name(fn))}",
                "value": _resource_name(fn),
            })

        # ── Container block ───────────────────────────────────────────────────
        container: dict = {
            "image": props.get("image", "gcr.io/cloudrun/hello"),
            "ports": {"container_port": int(props.get("port", 8080))},
            "resources": {
                "limits": {
                    "cpu":    str(props.get("cpu",    "1")),
                    "memory": str(props.get("memory", "512Mi")),
                },
                "startup_cpu_boost": bool(props.get("startup_cpu_boost", False)),
            },
        }
        if env_list:
            container["env"] = env_list

        # ── Template block ────────────────────────────────────────────────────
        template: dict = {
            "execution_environment":              props.get("execution_environment", "EXECUTION_ENVIRONMENT_GEN2"),
            "max_instance_request_concurrency":   int(props.get("concurrency", 80)),
            "timeout":                            f"{int(props.get('timeout_seconds', 300))}s",
            "containers":                         container,
            "scaling": {
                "min_instance_count": int(props.get("min_instances", 0)),
                "max_instance_count": int(props.get("max_instances", 10)),
            },
        }
        if sa_email:
            template["service_account"] = sa_email
        if vpc_block:
            template["vpc_access"] = vpc_block

        # ── Labels / Annotations ──────────────────────────────────────────────
        labels      = _parse_json_prop(props.get("labels",      ""))
        annotations = _parse_json_prop(props.get("annotations", ""))

        svc_body: dict = {
            "name":               name,
            "location":           r,
            "project":            "var.project_id",
            "deletion_protection": False,
            "ingress":            props.get("ingress", "INGRESS_TRAFFIC_INTERNAL_ONLY"),
            "template":           template,
        }
        if labels:
            svc_body["labels"] = labels
        if annotations:
            svc_body["annotations"] = annotations

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_run_v2_service", tf_id],
            body=svc_body,
            comment=f"Cloud Run service: {node_dict.get('label', name)}",
        ))

        if props.get("allow_unauthenticated", False):
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_cloud_run_v2_service_iam_member", f"{tf_id}_public_invoker"],
                body={
                    "project":  "var.project_id",
                    "location": r,
                    "name":     f"${{google_cloud_run_v2_service.{tf_id}.name}}",
                    "role":     "roles/run.invoker",
                    "member":   "allUsers",
                },
            ))

        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_uri"],
            body={
                "description": f"URI of Cloud Run service {name}",
                "value":       f"${{google_cloud_run_v2_service.{tf_id}.uri}}",
            },
        ))
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Terraform — static module interface
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return "cr"

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        r         = props.get("region", region)

        cv: dict[str, str] = {
            "name":                  f'"{_resource_name(node_dict)}"',
            "image":                 f'"{props.get("image", "gcr.io/cloudrun/hello")}"',
            "location":              f'"{r}"',
            "ingress":               f'"{props.get("ingress", "INGRESS_TRAFFIC_INTERNAL_ONLY")}"',
            "cpu":                   f'"{props.get("cpu", "1")}"',
            "memory":                f'"{props.get("memory", "512Mi")}"',
            "port":                  str(int(props.get("port", 8080))),
            "concurrency":           str(int(props.get("concurrency", 80))),
            "timeout_seconds":       str(int(props.get("timeout_seconds", 300))),
            "min_instances":         str(int(props.get("min_instances", 0))),
            "max_instances":         str(int(props.get("max_instances", 10))),
            "execution_environment": f'"{props.get("execution_environment", "EXECUTION_ENVIRONMENT_GEN2")}"',
            "startup_cpu_boost":     "true" if props.get("startup_cpu_boost") else "false",
            "vpc_egress":            f'"{props.get("vpc_egress", "PRIVATE_RANGES_ONLY")}"',
            "allow_unauthenticated": "true" if props.get("allow_unauthenticated") else "false",
        }

        # Service account
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            sa_node = _node_by_id(all_nodes, sa_id)
            if sa_node.get("props", {}).get("create_sa", True):
                cv["sa_email"] = f"module.sa_{_tf_name(sa_node)}.email"
            else:
                cv["sa_email"] = f'"{sa_node.get("props",{}).get("email","")}"'

        # VPC
        subnet_id = ctx.get("subnetwork_id", "")
        if subnet_id:
            sn_tf = _tf_name(_node_by_id(all_nodes, subnet_id))
            cv["vpc_network"]    = f"module.{sn_tf}.network_path"
            cv["vpc_subnetwork"] = f"module.{sn_tf}.subnetwork_path"
        elif props.get("vpc_network"):
            cv["vpc_network"]    = f'"{props["vpc_network"]}"'
            cv["vpc_subnetwork"] = f'"{props.get("vpc_subnetwork","")}"'

        # Env vars map
        env_lines: list[str] = []
        for tid in ctx.get("publishes_to_topics", []):
            t = _node_by_id(all_nodes, tid)
            env_lines.append(
                f'    PUBSUB_TOPIC_{_env_key(_resource_name(t))} = module.topic_{_tf_name(t)}.name'
            )
        for bid in ctx.get("bucket_ids", []):
            b = _node_by_id(all_nodes, bid)
            env_lines.append(
                f'    GCS_BUCKET_{_env_key(_resource_name(b))} = module.bucket_{_tf_name(b)}.name'
            )
        for qid in ctx.get("task_queue_ids", []):
            q = _node_by_id(all_nodes, qid)
            env_lines.append(
                f'    CLOUD_TASKS_QUEUE_{_env_key(_resource_name(q))} = module.queue_{_tf_name(q)}.name'
            )
        for fid in ctx.get("firestore_ids", []):
            fn = _node_by_id(all_nodes, fid)
            env_lines.append(
                f'    FIRESTORE_DATABASE_{_env_key(_resource_name(fn))} = "{_resource_name(fn)}"'
            )
        cv["env_vars"] = "{\n" + "\n".join(env_lines) + "\n  }" if env_lines else "{}"

        # Labels / Annotations as HCL maps
        labels = _parse_json_prop(props.get("labels", ""))
        if labels:
            lines = [f'    {k} = "{v}"' for k, v in labels.items()]
            cv["labels"] = "{\n" + "\n".join(lines) + "\n  }"

        annotations = _parse_json_prop(props.get("annotations", ""))
        if annotations:
            lines = [f'    {k} = "{v}"' for k, v in annotations.items()]
            cv["annotations"] = "{\n" + "\n".join(lines) + "\n  }"

        return cv

    # ──────────────────────────────────────────────────────────────────────────
    # Post-deploy
    # ──────────────────────────────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "service_url": pulumi_outputs.get("uri", "") or pulumi_outputs.get("service_url", ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="cloud_run_revision"'
                f' AND resource.labels.service_name="{name}"'
                f' AND resource.labels.location="{region}"'
            ),
            project=project,
        )