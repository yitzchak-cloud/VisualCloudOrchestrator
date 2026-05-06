"""
nodes/cloud_run.py — Cloud Run resource nodes (fully self-describing).

Bugs fixed vs previous version
--------------------------------
1. resolve_edges duplication:
   Each edge is now owned by exactly ONE node.
   Rule:  SOURCE node writes to ctx[src_id],
          TARGET node writes to ctx[tgt_id].

   CR→Bucket: CloudRunNode writes ctx[tgt_id]["writer_ids"]  (tells bucket who writes)
              GcsBucketNode writes ctx[tgt_id]["bucket_ids"]  (tells CR about bucket)
   These are DIFFERENT ctx keys so there is no conflict. But the old code also had
   GcsBucketNode writing bucket_ids AND writer_ids for the same edge — removed.

2. dag_deps cycle:
   bucket_ids removed from dag_deps.  Bucket name comes from the graph
   (props.name / label), not deployed_outputs.  Adding it as a dep created
   CR→Bucket→CR cycles.
   firestore_ids also removed — database_id defaults to "(default)".
   Only truly deploy-time deps are kept: topics, queues, visual APIs, SA, subnet.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
import re
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import (
    GCPNode, LogSource, Port, TFBlock, TFResult,
    _resource_name, _tf_name, _node_label, _node_name, _node_by_id,
)
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class CloudRunNode(GCPNode):
    name:          str  = ""
    image:         str  = ""
    memory:        str  = "512Mi"
    region:        str  = "me-west1"
    cpu:           str  = "1"
    min_instances: int  = 0
    max_instances: int  = 10
    port:          int  = 8080
    env_vars:      dict = field(default_factory=dict)
    service_url:   str  = ""

    params_schema: ClassVar = [
        {"key": "name",          "label": "Service Name",    "type": "text",   "default": "", "placeholder": "your-service-name"},
        {"key": "image",         "label": "Container Image", "type": "text",   "default": "", "placeholder": "gcr.io/project/image:tag"},
        {"key": "memory",        "label": "Memory",          "type": "select", "options": ["256Mi","512Mi","1Gi","2Gi","4Gi","8Gi"], "default": "512Mi"},
        {"key": "cpu",           "label": "CPU",             "type": "select", "options": ["1","2","4","8"], "default": "1"},
        {"key": "min_instances", "label": "Min Instances",   "type": "number", "default": 0},
        {"key": "max_instances", "label": "Max Instances",   "type": "number", "default": 10},
        {"key": "port",          "label": "Port",            "type": "number", "default": 8080},
        {"key": "region",        "label": "Region",          "type": "select", "options": ["me-west1","us-central1","us-east1"], "default": "me-west1"},
        {"key": "service_url",   "label": "Service URL",     "type": "text",   "default": "", "placeholder": "https://my-service.run.app"},
        {"key": "allow_unauthenticated", "label": "Allow Unauthenticated (public access)", "type": "checkbox", "default": False},
        {
            "key": "ingress", "label": "Ingress", "type": "select",
            "options": ["INGRESS_TRAFFIC_ALL", "INGRESS_TRAFFIC_INTERNAL_ONLY", "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"],
            "default": "INGRESS_TRAFFIC_INTERNAL_ONLY",
        },
        {"key": "vpc_network",    "label": "VPC Network (fallback)",    "type": "text", "default": "", "placeholder": "projects/HOST_PROJECT/global/networks/NETWORK"},
        {"key": "vpc_subnetwork", "label": "VPC Subnetwork (fallback)", "type": "text", "default": "", "placeholder": "projects/HOST_PROJECT/regions/REGION/subnetworks/SUBNET"},
    ]
    url_field: ClassVar = "service_url"

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
        Port("subnet",          PortType.NETWORK,          required=False),
        Port("http_callers",    PortType.HTTP_TARGET,      required=False, multi=True, multi_in=True),
        Port("task_queue",      PortType.TASK_QUEUE,       required=False, multi=True, multi_in=True),
        Port("secret",          PortType.SECRET,           multi=True,     multi_in=True),
        Port("MESSAGE",         PortType.MESSAGE,          multi=True,     multi_in=True),
        Port("storage",         PortType.STORAGE,          required=False, multi=True, multi_in=True),
        Port("iam_binding",     PortType.IAM_BINDING,      required=False, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to", PortType.TOPIC,   multi=True),
        Port("writes_to",    PortType.STORAGE, multi=True),
    ]
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloudRun"
    category:    ClassVar = "Compute"
    description: ClassVar = "Serverless container runtime"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ── CR is the SOURCE ──────────────────────────────────────────────────
        if src_id == self.node_id and src_type == "CloudRunNode":
            if tgt_type == "PubsubTopicNode":
                ctx[self.node_id].setdefault("publishes_to_topics", []).append(tgt_id)
                return True

            if tgt_type == "GcsBucketNode":
                # CR→Bucket: GcsBucketNode.resolve_edges sets writer_ids on the
                # bucket from its side. We do NOT set writer_ids here to avoid
                # double-counting when both nodes process this edge.
                # (No ctx write needed from this side for bucket output edges.)
                return True

            if tgt_type == "FirestoreNode":
                ctx[self.node_id].setdefault("firestore_ids", []).append(tgt_id)
                return True

        # ── CR is the TARGET ──────────────────────────────────────────────────
        if tgt_id == self.node_id:
            if src_type == "FirestoreNode":
                ctx[self.node_id].setdefault("firestore_ids", []).append(src_id)
                return True
            if src_type in ("CloudVisionNode", "CloudFunctionsNode", "ExternalApiNode"):
                ctx[self.node_id].setdefault("visual_api_ids", []).append(src_id)
                return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        """
        Only nodes whose DEPLOYED OUTPUT is needed at Pulumi build time.

        bucket_ids   → NOT a dep: name known from graph props/label.
        firestore_ids → NOT a dep: database_id defaults to "(default)".
        topic_ids    → dep: need deployed topic name for env var value.
        task_queue   → dep: need deployed queue name for env var value.
        visual_apis  → dep: need deployed URL.
        subnet, SA   → deps: need deployed paths / email.
        """
        deps = list(ctx.get("publishes_to_topics", []))
        deps += ctx.get("task_queue_ids",  [])
        deps += ctx.get("visual_api_ids",  [])
        if ctx.get("subnetwork_id"):
            deps.append(ctx["subnetwork_id"])
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        subnet_id       = ctx.get("subnetwork_id", "")
        subnet_outputs  = deployed_outputs.get(subnet_id, {})
        network_path    = subnet_outputs.get("network_path")    or props.get("vpc_network",    "")
        subnetwork_path = subnet_outputs.get("subnetwork_path") or props.get("vpc_subnetwork", "")

        if not network_path or not subnetwork_path:
            logger.warning("CloudRunNode %s: no VPC resolved", self.node_id)

        sa_email = deployed_outputs.get(ctx.get("service_account_id", ""), {}).get("email", "")

        topic_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="PUBSUB_TOPIC_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, tid).upper()),
                value=deployed_outputs.get(tid, {}).get("name", ""),
            )
            for tid in ctx.get("publishes_to_topics", [])
        ]
        sub_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="PUBSUB_SUBSCRIPTION_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, sid).upper()),
                value=_resource_name(next((n for n in all_nodes if n["id"] == sid), {})),
            )
            for sid in ctx.get("receives_from_subs", [])
        ]
        # Bucket name from graph (not deployed_outputs) — no deploy dep needed
        bucket_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()),
                value=_resource_name(_node_by_id(all_nodes, bid)),
            )
            for bid in ctx.get("bucket_ids", [])
        ]
        queue_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="CLOUD_TASKS_QUEUE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, qid).upper()),
                value=deployed_outputs.get(qid, {}).get("queue_name", ""),
            )
            for qid in ctx.get("task_queue_ids", [])
        ]
        firestore_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="FIRESTORE_DATABASE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, fid).upper()),
                value=deployed_outputs.get(fid, {}).get("database_id", "(default)"),
            )
            for fid in ctx.get("firestore_ids", [])
        ]
        visual_api_envs = []
        for vid in ctx.get("visual_api_ids", []):
            out   = deployed_outputs.get(vid, {})
            url   = out.get("url", "")
            vname = out.get("name", _node_name(all_nodes, vid))
            key   = re.sub(r"[^A-Z0-9]", "_", vname.upper())
            if url:
                visual_api_envs.append(
                    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(name=f"API_URL_{key}", value=url)
                )

        all_envs = topic_envs + sub_envs + bucket_envs + queue_envs + firestore_envs + visual_api_envs

        def program() -> None:
            allow_unauth = props.get("allow_unauthenticated", False)
            ingress      = props.get("ingress", "INGRESS_TRAFFIC_INTERNAL_ONLY")

            vpc_access = None
            if network_path and subnetwork_path:
                vpc_access = gcp.cloudrunv2.ServiceTemplateVpcAccessArgs(
                    egress="PRIVATE_RANGES_ONLY",
                    network_interfaces=[
                        gcp.cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=network_path, subnetwork=subnetwork_path,
                        )
                    ],
                )

            svc = gcp.cloudrunv2.Service(
                self.node_id,
                name=_resource_name(node_dict),
                location=region,
                project=project,
                deletion_protection=False,
                ingress=ingress,
                template=gcp.cloudrunv2.ServiceTemplateArgs(
                    service_account=sa_email or None,
                    containers=[gcp.cloudrunv2.ServiceTemplateContainerArgs(
                        image=props.get("image", "gcr.io/cloudrun/hello"),
                        envs=all_envs or None,
                    )],
                    vpc_access=vpc_access,
                ),
            )
            if allow_unauth:
                gcp.cloudrun.IamMember(
                    f"{self.node_id}-public", location=region, project=project,
                    service=svc.name, role="roles/run.invoker", member="allUsers",
                )
            pulumi.export("uri",  svc.uri)
            pulumi.export("name", svc.name)
            pulumi.export("id",   svc.id)

        return program

    # ------------------------------------------------------------------
    # Terraform blocks
    # ------------------------------------------------------------------

    def terraform_blocks(self, ctx, project, region, all_nodes) -> TFResult:
        result    = TFResult()
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        name      = _resource_name(node_dict)
        tf_id     = _tf_name(node_dict)
        r         = props.get("region", region)

        vpc_block: dict = {}
        subnet_id = ctx.get("subnetwork_id", "")
        if subnet_id:
            sn_tf = _tf_name(_node_by_id(all_nodes, subnet_id))
            vpc_block = {
                "egress": "PRIVATE_RANGES_ONLY",
                "network_interfaces": {
                    "network":    f"${{google_compute_subnetwork.{sn_tf}.network}}",
                    "subnetwork": f"${{google_compute_subnetwork.{sn_tf}.self_link}}",
                },
            }
        else:
            if props.get("vpc_network") and props.get("vpc_subnetwork"):
                vpc_block = {
                    "egress": "PRIVATE_RANGES_ONLY",
                    "network_interfaces": {
                        "network": props["vpc_network"], "subnetwork": props["vpc_subnetwork"],
                    },
                }

        sa_email = ""
        sa_id    = ctx.get("service_account_id", "")
        if sa_id:
            sa_node = _node_by_id(all_nodes, sa_id)
            sa_email = (
                f"${{google_service_account.{_tf_name(sa_node)}.email}}"
                if sa_node.get("props", {}).get("create_sa", True)
                else sa_node.get("props", {}).get("email", "")
            )

        env_list = []
        for tid in ctx.get("publishes_to_topics", []):
            t = _node_by_id(all_nodes, tid)
            env_list.append({"name": "PUBSUB_TOPIC_" + _resource_name(t).upper().replace("-", "_"),
                              "value": f"${{google_pubsub_topic.{_tf_name(t)}.name}}"})
        for bid in ctx.get("bucket_ids", []):
            b = _node_by_id(all_nodes, bid)
            env_list.append({"name": "GCS_BUCKET_" + _resource_name(b).upper().replace("-", "_"),
                              "value": f"${{google_storage_bucket.{_tf_name(b)}.name}}"})
        for qid in ctx.get("task_queue_ids", []):
            q = _node_by_id(all_nodes, qid)
            env_list.append({"name": "CLOUD_TASKS_QUEUE_" + _resource_name(q).upper().replace("-", "_"),
                              "value": f"${{google_cloud_tasks_queue.{_tf_name(q)}.name}}"})
        for fid in ctx.get("firestore_ids", []):
            f_n = _node_by_id(all_nodes, fid)
            env_list.append({"name": "FIRESTORE_DATABASE_" + _resource_name(f_n).upper().replace("-", "_"),
                              "value": _resource_name(f_n)})

        container: dict = {"image": props.get("image", "gcr.io/cloudrun/hello")}
        if env_list:
            container["env"] = env_list
        template: dict = {
            "containers": container,
            "scaling": {
                "min_instance_count": int(props.get("min_instances", 0)),
                "max_instance_count": int(props.get("max_instances", 10)),
            },
        }
        if sa_email:
            template["service_account"] = sa_email
        if vpc_block:
            template["vpc_access"] = vpc_block

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_run_v2_service", tf_id],
            body={
                "name": name, "location": r, "project": "var.project_id",
                "deletion_protection": False,
                "ingress": props.get("ingress", "INGRESS_TRAFFIC_INTERNAL_ONLY"),
                "template": template,
            },
            comment=f"Cloud Run service: {node_dict.get('label', name)}",
        ))
        if props.get("allow_unauthenticated", False):
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_cloud_run_v2_service_iam_member", f"{tf_id}_public_invoker"],
                body={
                    "project": "var.project_id", "location": r,
                    "name":   f"${{google_cloud_run_v2_service.{tf_id}.name}}",
                    "role":   "roles/run.invoker", "member": "allUsers",
                },
            ))
        result.outputs.append(TFBlock(
            block_type="output", labels=[f"{tf_id}_uri"],
            body={"description": f"URI of Cloud Run service {name}",
                  "value": f"${{google_cloud_run_v2_service.{tf_id}.uri}}"},
        ))
        return result

    # ------------------------------------------------------------------
    # Post-deploy
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"service_url": pulumi_outputs.get("uri", "")}

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