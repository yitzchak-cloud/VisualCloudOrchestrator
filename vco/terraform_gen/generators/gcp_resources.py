"""
terraform_gen/generators/gcp_resources.py
==========================================
Generators for:
  - GcsBucketNode          → google_storage_bucket (+ IAM bindings)
  - VpcNetworkNode         → (reference only, no resource created)
  - SubnetworkNode         → (reference only, no resource created)
  - ServiceAccountNode     → google_service_account
  - CloudSchedulerNode     → google_cloud_scheduler_job
  - CloudTasksQueueNode    → google_cloud_tasks_queue
  - EventarcTriggerNode    → google_eventarc_trigger
  - WorkflowNode           → google_workflows_workflow
"""
from __future__ import annotations

from .base import BaseGenerator, GeneratorResult, TFBlock


# ── GCS Bucket ────────────────────────────────────────────────────────────────

class GcsBucketGenerator(BaseGenerator):
    handled_types = {"GcsBucketNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        body: dict = {
            "name":          name,
            "project":       "var.project_id",
            "location":      props.get("location", "US"),
            "storage_class": props.get("storage_class", "STANDARD"),
            "force_destroy": True,
        }
        if props.get("versioning"):
            body["versioning"] = {"enabled": True}
        if props.get("uniform_access", True):
            body["uniform_bucket_level_access"] = True
        if props.get("lifecycle_age"):
            body["lifecycle_rule"] = {
                "condition": {"age": int(props["lifecycle_age"])},
                "action":    {"type": "Delete"},
            }
        if props.get("public_access"):
            body["public_access_prevention"] = "inherited"

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_storage_bucket", tf_id],
            body=body,
            comment=f"GCS Bucket: {node.get('label', name)}",
        ))

        # IAM: grant objectCreator to each writer SA
        for writer_id in ctx.get("writer_ids", []):
            writer_node = self.node_by_id(all_nodes, writer_id)
            writer_type = writer_node.get("type", "")
            sa_id = None

            # Attempt to resolve the SA of the writer
            # (writer_ctx would have service_account_id if wired)
            w_sa = ""
            for e in edges:
                if e.get("target") == writer_id and e.get("targetHandle") == "service_account":
                    sa_node = self.node_by_id(all_nodes, e["source"])
                    if sa_node:
                        w_sa = f"${{google_service_account.{self.tf_name(sa_node)}.email}}"
                    break

            if w_sa:
                iam_tf_id = f"{tf_id}_writer_{self.tf_name(writer_node)}"
                result.resources.append(TFBlock(
                    block_type="resource",
                    labels=["google_storage_bucket_iam_member", iam_tf_id],
                    body={
                        "bucket": f"${{google_storage_bucket.{tf_id}.name}}",
                        "role":   "roles/storage.objectCreator",
                        "member": f"serviceAccount:{w_sa}",
                    },
                    comment=f"Grant {writer_node.get('label','')} write access to bucket",
                ))

        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_name"],
            body={
                "description": f"GCS bucket name: {name}",
                "value":       f"${{google_storage_bucket.{tf_id}.name}}",
            },
        ))
        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_url"],
            body={
                "description": f"GCS bucket URL: {name}",
                "value":       f"${{google_storage_bucket.{tf_id}.url}}",
            },
        ))
        return result


# ── VPC Network (reference only) ──────────────────────────────────────────────

class VpcNetworkGenerator(BaseGenerator):
    """VpcNetworkNode creates NO GCP resource — it's a reference to an existing VPC."""
    handled_types = {"VpcNetworkNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props = node.get("props", {})
        tf_id = self.tf_name(node)

        # Expose the network as a data source
        host_project  = props.get("host_project", "var.project_id")
        network_name  = props.get("network_name", "default")

        result.data.append(TFBlock(
            block_type="data",
            labels=["google_compute_network", tf_id],
            body={
                "name":    network_name,
                "project": host_project,
            },
            comment=f"VPC Network reference: {node.get('label', network_name)}",
        ))
        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_self_link"],
            body={
                "description": f"Self-link for VPC network {network_name}",
                "value":       f"${{data.google_compute_network.{tf_id}.self_link}}",
            },
        ))
        return result


# ── Subnetwork (reference only) ───────────────────────────────────────────────

class SubnetworkGenerator(BaseGenerator):
    """SubnetworkNode creates NO GCP resource — it's a reference to an existing subnet."""
    handled_types = {"SubnetworkNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props   = node.get("props", {})
        tf_id   = self.tf_name(node)
        r       = props.get("region", region)

        # Resolve host project from parent VpcNetworkNode if wired
        host_project = "var.project_id"
        vpc_id = ctx.get("vpc_network_id", "")
        if vpc_id:
            vpc_node    = self.node_by_id(all_nodes, vpc_id)
            host_project = vpc_node.get("props", {}).get("host_project", "var.project_id")

        subnetwork_name = props.get("subnetwork_name", self.resource_name(node))

        result.data.append(TFBlock(
            block_type="data",
            labels=["google_compute_subnetwork", tf_id],
            body={
                "name":    subnetwork_name,
                "region":  r,
                "project": host_project,
            },
            comment=f"Subnetwork reference: {node.get('label', subnetwork_name)}",
        ))
        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_self_link"],
            body={
                "description": f"Self-link for subnetwork {subnetwork_name}",
                "value":       f"${{data.google_compute_subnetwork.{tf_id}.self_link}}",
            },
        ))
        return result


# ── Service Account ───────────────────────────────────────────────────────────

class ServiceAccountGenerator(BaseGenerator):
    handled_types = {"ServiceAccountNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        tf_id  = self.tf_name(node)

        create_sa    = props.get("create_sa", True)
        account_id   = props.get("account_id", self.resource_name(node))
        display_name = props.get("display_name", node.get("label", account_id))

        if create_sa:
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_service_account", tf_id],
                body={
                    "account_id":   account_id,
                    "display_name": display_name,
                    "project":      "var.project_id",
                },
                comment=f"Service Account: {node.get('label', account_id)}",
            ))
            sa_email_ref = f"${{google_service_account.{tf_id}.email}}"
        else:
            # Reference only — use email prop directly
            sa_email_ref = props.get("email", "")

        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_email"],
            body={
                "description": f"Email of service account {account_id}",
                "value":       sa_email_ref,
            },
        ))
        return result


# ── Cloud Scheduler ───────────────────────────────────────────────────────────

class CloudSchedulerGenerator(BaseGenerator):
    handled_types = {"CloudSchedulerNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        sa_email = ""
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            sa_node  = self.node_by_id(all_nodes, sa_id)
            sa_email = f"${{google_service_account.{self.tf_name(sa_node)}.email}}"

        schedule  = props.get("schedule", "0 * * * *")
        timezone  = props.get("timezone", "UTC")
        http_path = props.get("http_path", "/")
        method    = props.get("http_method", "POST").upper()

        for i, target_id in enumerate(ctx.get("target_run_ids", [])):
            cr_node = self.node_by_id(all_nodes, target_id)
            cr_uri  = f"${{google_cloud_run_v2_service.{self.tf_name(cr_node)}.uri}}{http_path}"

            oidc_block = {}
            if sa_email:
                oidc_block = {
                    "service_account_email": sa_email,
                    "audience":              f"${{google_cloud_run_v2_service.{self.tf_name(cr_node)}.uri}}",
                }

            job_body: dict = {
                "name":       f"{name}-cr-{i}" if i > 0 else name,
                "project":    "var.project_id",
                "region":     region,
                "schedule":   schedule,
                "time_zone":  timezone,
                "http_target": {
                    "uri":         cr_uri,
                    "http_method": method,
                },
            }
            if oidc_block:
                job_body["http_target"]["oidc_token"] = oidc_block
            if int(props.get("retry_count", 0)) > 0:
                job_body["retry_config"] = {"retry_count": int(props["retry_count"])}

            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_cloud_scheduler_job", f"{tf_id}_cr_{i}"],
                body=job_body,
                comment=f"Scheduler → Cloud Run: {cr_node.get('label', target_id)}",
            ))

        # Pub/Sub targets
        for i, topic_id in enumerate(ctx.get("target_topic_ids", [])):
            t_node = self.node_by_id(all_nodes, topic_id)
            job_body = {
                "name":      f"{name}-ps-{i}" if i > 0 else f"{name}-ps",
                "project":   "var.project_id",
                "region":    region,
                "schedule":  schedule,
                "time_zone": timezone,
                "pubsub_target": {
                    "topic_name": f"${{google_pubsub_topic.{self.tf_name(t_node)}.id}}",
                    "data":       props.get("pubsub_message", "e30K"),  # base64("{}")
                },
            }
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_cloud_scheduler_job", f"{tf_id}_ps_{i}"],
                body=job_body,
                comment=f"Scheduler → Pub/Sub: {t_node.get('label', topic_id)}",
            ))

        # Cloud Run Job targets
        for i, job_id in enumerate(ctx.get("target_job_ids", [])):
            job_node = self.node_by_id(all_nodes, job_id)
            job_body = {
                "name":      f"{name}-job-{i}" if i > 0 else f"{name}-job",
                "project":   "var.project_id",
                "region":    region,
                "schedule":  schedule,
                "time_zone": timezone,
                "http_target": {
                    "uri":         f"https://run.googleapis.com/v2/projects/${{var.project_id}}/locations/{region}/jobs/${{google_cloud_run_v2_job.{self.tf_name(job_node)}.name}}:run",
                    "http_method": "POST",
                    "oauth_token": {"service_account_email": sa_email} if sa_email else {},
                },
            }
            result.resources.append(TFBlock(
                block_type="resource",
                labels=["google_cloud_scheduler_job", f"{tf_id}_job_{i}"],
                body=job_body,
                comment=f"Scheduler → Cloud Run Job: {job_node.get('label', job_id)}",
            ))

        return result


# ── Cloud Tasks Queue ──────────────────────────────────────────────────────────

class CloudTasksQueueGenerator(BaseGenerator):
    handled_types = {"CloudTasksQueueNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        body: dict = {
            "name":     name,
            "project":  "var.project_id",
            "location": region,
        }
        rate_limits = {}
        if props.get("max_dispatches_per_second"):
            rate_limits["max_dispatches_per_second"] = float(props["max_dispatches_per_second"])
        if props.get("max_concurrent"):
            rate_limits["max_concurrent_dispatches"] = int(props["max_concurrent"])
        if rate_limits:
            body["rate_limits"] = rate_limits

        retry_config = {}
        if props.get("max_attempts"):
            retry_config["max_attempts"] = int(props["max_attempts"])
        if props.get("min_backoff"):
            retry_config["min_backoff"] = props["min_backoff"]
        if props.get("max_backoff"):
            retry_config["max_backoff"] = props["max_backoff"]
        if retry_config:
            body["retry_config"] = retry_config

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_cloud_tasks_queue", tf_id],
            body=body,
            comment=f"Cloud Tasks Queue: {node.get('label', name)}",
        ))
        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_name"],
            body={
                "description": f"Cloud Tasks queue name: {name}",
                "value":       f"${{google_cloud_tasks_queue.{tf_id}.name}}",
            },
        ))
        return result


# ── Eventarc Trigger ──────────────────────────────────────────────────────────

class EventarcTriggerGenerator(BaseGenerator):
    handled_types = {"EventarcTriggerNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        sa_email = ""
        sa_id = ctx.get("service_account_id", "")
        if sa_id:
            sa_node  = self.node_by_id(all_nodes, sa_id)
            sa_email = f"${{google_service_account.{self.tf_name(sa_node)}.email}}"

        # Resolve target Cloud Run service
        destination: dict = {}
        for run_id in ctx.get("target_run_ids", []):
            cr_node = self.node_by_id(all_nodes, run_id)
            destination = {
                "cloud_run_service": {
                    "service": f"${{google_cloud_run_v2_service.{self.tf_name(cr_node)}.name}}",
                    "region":  region,
                    "path":    props.get("http_path", "/"),
                }
            }
            break

        # Detect trigger type
        topic_id  = ctx.get("topic_source_id", "")
        bucket_id = ctx.get("bucket_source_id", "")

        if topic_id:
            topic_node = self.node_by_id(all_nodes, topic_id)
            matching = [{
                "type":       "google.cloud.pubsub.topic.v1.messagePublished",
                "service":    "pubsub.googleapis.com",
                "attributes": {
                    "topic": f"${{google_pubsub_topic.{self.tf_name(topic_node)}.id}}",
                },
            }]
        elif bucket_id:
            bucket_node   = self.node_by_id(all_nodes, bucket_id)
            gcs_evt_type  = props.get("gcs_event_type", "google.cloud.storage.object.v1.finalized")
            matching = [{
                "type":       gcs_evt_type,
                "service":    "storage.googleapis.com",
                "attributes": {
                    "bucket": f"${{google_storage_bucket.{self.tf_name(bucket_node)}.name}}",
                },
            }]
        else:
            matching = [{
                "type":    props.get("direct_event_type", "google.cloud.audit.log.v1.written"),
                "service": props.get("direct_service", "cloudresourcemanager.googleapis.com"),
            }]

        body: dict = {
            "name":            name,
            "project":         "var.project_id",
            "location":        region,
            "matching_criteria": matching,
            "destination":     destination,
        }
        if sa_email:
            body["service_account"] = sa_email

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_eventarc_trigger", tf_id],
            body=body,
            comment=f"Eventarc Trigger: {node.get('label', name)}",
        ))
        return result


# ── Workflows ─────────────────────────────────────────────────────────────────

class WorkflowGenerator(BaseGenerator):
    handled_types = {"WorkflowNode"}

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
            sa_email = f"${{google_service_account.{self.tf_name(sa_node)}.email}}"

        # Build a minimal workflow YAML if not provided
        source_yaml = props.get("source_yaml", "")
        if not source_yaml:
            steps = []
            for run_id in ctx.get("target_run_ids", []):
                cr_node = self.node_by_id(all_nodes, run_id)
                cr_name = self.resource_name(cr_node)
                steps.append(
                    f"  - call_{cr_name}:\n"
                    f"      call: http.post\n"
                    f"      args:\n"
                    f"        url: ${{{{sys.get_env(\"GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID\")}}}}\n"
                    f"        auth:\n"
                    f"          type: OIDC\n"
                )
            source_yaml = "main:\n  steps:\n" + ("".join(steps) if steps else "  - init:\n      return: done\n")

        body: dict = {
            "name":         name,
            "project":      "var.project_id",
            "region":       r,
            "source_contents": source_yaml,
        }
        if sa_email:
            body["service_account"] = sa_email

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_workflows_workflow", tf_id],
            body=body,
            comment=f"Cloud Workflow: {node.get('label', name)}",
        ))
        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_name"],
            body={
                "description": f"Workflow name: {name}",
                "value":       f"${{google_workflows_workflow.{tf_id}.name}}",
            },
        ))
        return result
