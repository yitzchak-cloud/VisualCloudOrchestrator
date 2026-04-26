"""
terraform_gen/generators/cloud_run.py
======================================
Generates Terraform HCL for:
  - CloudRunNode   → google_cloud_run_v2_service
  - CloudRunJobNode → google_cloud_run_v2_job
"""
from __future__ import annotations

from .base import BaseGenerator, GeneratorResult, TFBlock


class CloudRunGenerator(BaseGenerator):
    handled_types = {"CloudRunNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props = node.get("props", {})
        name  = self.resource_name(node)
        tf_id = self.tf_name(node)
        r     = props.get("region", region)

        # ── VPC access ─────────────────────────────────────────────────────────
        vpc_block = {}
        subnet_id = ctx.get("subnetwork_id", "")
        if subnet_id:
            subnet_node = self.node_by_id(all_nodes, subnet_id)
            subnet_tf   = self.tf_name(subnet_node)
            network_path  = f"${{google_compute_subnetwork.{subnet_tf}.network}}"
            subnetwork_path = f"${{google_compute_subnetwork.{subnet_tf}.self_link}}"
        else:
            network_path    = props.get("vpc_network", "")
            subnetwork_path = props.get("vpc_subnetwork", "")

        if network_path and subnetwork_path:
            vpc_block = {
                "egress": "PRIVATE_RANGES_ONLY",
                "network_interfaces": {
                    "network":    network_path,
                    "subnetwork": subnetwork_path,
                },
            }

        # ── Service account ─────────────────────────────────────────────────────
        sa_email = ""
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            sa_node   = self.node_by_id(all_nodes, sa_id)
            sa_create = sa_node.get("props", {}).get("create_sa", True)
            sa_tf     = self.tf_name(sa_node)
            if sa_create:
                sa_email = f"${{google_service_account.{sa_tf}.email}}"
            else:
                sa_email = sa_node.get("props", {}).get("email", "")

        # ── Env vars (from wired topics / buckets / queues) ────────────────────
        env_list = []
        for tid in ctx.get("publishes_to_topics", []):
            t = self.node_by_id(all_nodes, tid)
            k = "PUBSUB_TOPIC_" + self.resource_name(t).upper().replace("-", "_")
            env_list.append({"name": k, "value": f"${{google_pubsub_topic.{self.tf_name(t)}.name}}"})

        for bid in ctx.get("bucket_ids", []):
            b = self.node_by_id(all_nodes, bid)
            k = "GCS_BUCKET_" + self.resource_name(b).upper().replace("-", "_")
            env_list.append({"name": k, "value": f"${{google_storage_bucket.{self.tf_name(b)}.name}}"})

        for qid in ctx.get("task_queue_ids", []):
            q = self.node_by_id(all_nodes, qid)
            k = "CLOUD_TASKS_QUEUE_" + self.resource_name(q).upper().replace("-", "_")
            env_list.append({"name": k, "value": f"${{google_cloud_tasks_queue.{self.tf_name(q)}.name}}"})

        # ── Build template block ────────────────────────────────────────────────
        container: dict = {
            "image": props.get("image", "gcr.io/cloudrun/hello"),
        }
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

        # ── Resource block ──────────────────────────────────────────────────────
        body = {
            "name":               name,
            "location":           r,
            "project":            "var.project_id",
            "deletion_protection": False,
            "ingress":            "INGRESS_TRAFFIC_INTERNAL_ONLY",
            "template":           template,
        }

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_run_v2_service", tf_id],
            body=body,
            comment=f"Cloud Run service: {node.get('label', name)}",
        ))

        # ── Output: service URI ─────────────────────────────────────────────────
        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_uri"],
            body={
                "description": f"URI of Cloud Run service {name}",
                "value":       f"${{google_cloud_run_v2_service.{tf_id}.uri}}",
            },
        ))

        # ── IAM: allow unauthenticated (optional — only if no SA on callers) ───
        # Users can uncomment this block in the generated code
        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_run_v2_service_iam_member", f"{tf_id}_invoker"],
            body={
                "project":  "var.project_id",
                "location": r,
                "name":     f"${{google_cloud_run_v2_service.{tf_id}.name}}",
                "role":     "roles/run.invoker",
                "member":   "allUsers",
                "_comment": "# Remove or restrict this for private services",
            },
            comment="# Uncomment to allow public (unauthenticated) access:",
        ))

        return result


class CloudRunJobGenerator(BaseGenerator):
    handled_types = {"CloudRunJobNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)
        r      = props.get("region", region)

        sa_email = ""
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            sa_node  = self.node_by_id(all_nodes, sa_id)
            sa_tf    = self.tf_name(sa_node)
            sa_email = f"${{google_service_account.{sa_tf}.email}}"

        template: dict = {
            "task_count":   int(props.get("task_count", 1)),
            "parallelism":  int(props.get("parallelism", 1)),
            "template": {
                "max_retries": int(props.get("max_retries", 3)),
                "containers":  {"image": props.get("image", "gcr.io/cloudrun/hello")},
            },
        }
        if sa_email:
            template["template"]["service_account"] = sa_email

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_run_v2_job", tf_id],
            body={
                "name":     name,
                "location": r,
                "project":  "var.project_id",
                "template": template,
            },
            comment=f"Cloud Run Job: {node.get('label', name)}",
        ))

        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_job_name"],
            body={
                "description": f"Name of Cloud Run Job {name}",
                "value":       f"${{google_cloud_run_v2_job.{tf_id}.name}}",
            },
        ))
        return result
