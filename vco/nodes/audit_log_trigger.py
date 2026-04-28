"""
nodes/audit_log_trigger.py — Audit Log Eventarc Trigger Node

Topology
--------
  AuditLogTriggerNode ──(EVENT)──► CloudRunNode

UX Flow (cascading dropdowns, like GCP Console):
  1. User picks "Event Provider"  (e.g. "Cloud Storage")
  2. "Method" dropdown auto-populates with methods for that provider
  3. Optional: resourceName path-pattern filter

Pulumi wiring
-------------
  Always uses:
    type=google.cloud.audit.log.v1.written
    serviceName=<from catalog>
    methodName=<from catalog>
  Optionally:
    resourceName=<user-supplied path pattern>

The destination is always the wired CloudRunNode.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

# ── Audit Log catalog ─────────────────────────────────────────────────────────
# Structure: { display_label: { service: str, methods: [ {label, value} ] } }
# Values come from GCP Audit Log serviceName / methodName docs.
AUDIT_LOG_CATALOG: dict[str, dict] = {
    "Cloud Storage": {
        "service": "storage.googleapis.com",
        "methods": [
            {"label": "Create Object",          "value": "storage.objects.create"},
            {"label": "Delete Object",          "value": "storage.objects.delete"},
            {"label": "Get Object",             "value": "storage.objects.get"},
            {"label": "List Objects",           "value": "storage.objects.list"},
            {"label": "Update Object",          "value": "storage.objects.update"},
            {"label": "Create Bucket",          "value": "storage.buckets.create"},
            {"label": "Delete Bucket",          "value": "storage.buckets.delete"},
            {"label": "Get Bucket",             "value": "storage.buckets.get"},
            {"label": "Update Bucket",          "value": "storage.buckets.update"},
        ],
    },
    "BigQuery": {
        "service": "bigquery.googleapis.com",
        "methods": [
            {"label": "Insert Job (Query/Load)", "value": "google.cloud.bigquery.v2.JobService.InsertJob"},
            {"label": "Job Completed",           "value": "jobservice.jobcompleted"},
            {"label": "Create Table",            "value": "google.cloud.bigquery.v2.TableService.InsertTable"},
            {"label": "Delete Table",            "value": "google.cloud.bigquery.v2.TableService.DeleteTable"},
            {"label": "Create Dataset",          "value": "google.cloud.bigquery.v2.DatasetService.InsertDataset"},
            {"label": "Delete Dataset",          "value": "google.cloud.bigquery.v2.DatasetService.DeleteDataset"},
            {"label": "Run Query (legacy)",      "value": "google.cloud.bigquery.v2.JobService.Query"},
        ],
    },
    "Cloud Run": {
        "service": "run.googleapis.com",
        "methods": [
            {"label": "Create Service",          "value": "google.cloud.run.v2.Services.CreateService"},
            {"label": "Update Service",          "value": "google.cloud.run.v2.Services.UpdateService"},
            {"label": "Delete Service",          "value": "google.cloud.run.v2.Services.DeleteService"},
            {"label": "Create Revision",         "value": "google.cloud.run.v2.Revisions.DeleteRevision"},
            {"label": "Run Job",                 "value": "google.cloud.run.v2.Jobs.RunJob"},
            {"label": "Create Job",              "value": "google.cloud.run.v2.Jobs.CreateJob"},
            {"label": "Delete Job",              "value": "google.cloud.run.v2.Jobs.DeleteJob"},
        ],
    },
    "Pub/Sub": {
        "service": "pubsub.googleapis.com",
        "methods": [
            {"label": "Create Topic",            "value": "google.pubsub.v1.Publisher.CreateTopic"},
            {"label": "Delete Topic",            "value": "google.pubsub.v1.Publisher.DeleteTopic"},
            {"label": "Create Subscription",     "value": "google.pubsub.v1.Subscriber.CreateSubscription"},
            {"label": "Delete Subscription",     "value": "google.pubsub.v1.Subscriber.DeleteSubscription"},
            {"label": "Publish Message",         "value": "google.pubsub.v1.Publisher.Publish"},
        ],
    },
    "Cloud SQL": {
        "service": "cloudsql.googleapis.com",
        "methods": [
            {"label": "Create Instance",         "value": "cloudsql.instances.create"},
            {"label": "Delete Instance",         "value": "cloudsql.instances.delete"},
            {"label": "Update Instance",         "value": "cloudsql.instances.update"},
            {"label": "Create Database",         "value": "cloudsql.databases.create"},
            {"label": "Delete Database",         "value": "cloudsql.databases.delete"},
            {"label": "Create Backup",           "value": "cloudsql.backupRuns.create"},
            {"label": "Failover",                "value": "cloudsql.instances.failover"},
        ],
    },
    "Cloud Functions": {
        "service": "cloudfunctions.googleapis.com",
        "methods": [
            {"label": "Create Function",         "value": "google.cloud.functions.v2.FunctionService.CreateFunction"},
            {"label": "Update Function",         "value": "google.cloud.functions.v2.FunctionService.UpdateFunction"},
            {"label": "Delete Function",         "value": "google.cloud.functions.v2.FunctionService.DeleteFunction"},
        ],
    },
    "Kubernetes Engine (GKE)": {
        "service": "container.googleapis.com",
        "methods": [
            {"label": "Create Cluster",          "value": "google.container.v1.ClusterManager.CreateCluster"},
            {"label": "Delete Cluster",          "value": "google.container.v1.ClusterManager.DeleteCluster"},
            {"label": "Update Cluster",          "value": "google.container.v1.ClusterManager.UpdateCluster"},
            {"label": "Create Node Pool",        "value": "google.container.v1.ClusterManager.CreateNodePool"},
            {"label": "Delete Node Pool",        "value": "google.container.v1.ClusterManager.DeleteNodePool"},
        ],
    },
    "IAM": {
        "service": "iam.googleapis.com",
        "methods": [
            {"label": "Create Service Account",  "value": "google.iam.admin.v1.CreateServiceAccount"},
            {"label": "Delete Service Account",  "value": "google.iam.admin.v1.DeleteServiceAccount"},
            {"label": "Create Service Account Key", "value": "google.iam.admin.v1.CreateServiceAccountKey"},
            {"label": "Set IAM Policy",          "value": "SetIamPolicy"},
        ],
    },
    "Secret Manager": {
        "service": "secretmanager.googleapis.com",
        "methods": [
            {"label": "Create Secret",           "value": "google.cloud.secretmanager.v1.SecretManagerService.CreateSecret"},
            {"label": "Add Secret Version",      "value": "google.cloud.secretmanager.v1.SecretManagerService.AddSecretVersion"},
            {"label": "Access Secret Version",   "value": "google.cloud.secretmanager.v1.SecretManagerService.AccessSecretVersion"},
            {"label": "Delete Secret",           "value": "google.cloud.secretmanager.v1.SecretManagerService.DeleteSecret"},
        ],
    },
    "Compute Engine": {
        "service": "compute.googleapis.com",
        "methods": [
            {"label": "Insert Instance",         "value": "v1.compute.instances.insert"},
            {"label": "Delete Instance",         "value": "v1.compute.instances.delete"},
            {"label": "Start Instance",          "value": "v1.compute.instances.start"},
            {"label": "Stop Instance",           "value": "v1.compute.instances.stop"},
            {"label": "Insert Disk",             "value": "v1.compute.disks.insert"},
            {"label": "Delete Disk",             "value": "v1.compute.disks.delete"},
        ],
    },
    "Artifact Registry": {
        "service": "artifactregistry.googleapis.com",
        "methods": [
            {"label": "Create Repository",       "value": "google.devtools.artifactregistry.v1.ArtifactRegistry.CreateRepository"},
            {"label": "Delete Repository",       "value": "google.devtools.artifactregistry.v1.ArtifactRegistry.DeleteRepository"},
            {"label": "Create Tag",              "value": "google.devtools.artifactregistry.v1.ArtifactRegistry.CreateTag"},
            {"label": "Delete Tag",              "value": "google.devtools.artifactregistry.v1.ArtifactRegistry.DeleteTag"},
        ],
    },
    "Cloud Spanner": {
        "service": "spanner.googleapis.com",
        "methods": [
            {"label": "Create Instance",         "value": "google.spanner.admin.instance.v1.InstanceAdmin.CreateInstance"},
            {"label": "Delete Instance",         "value": "google.spanner.admin.instance.v1.InstanceAdmin.DeleteInstance"},
            {"label": "Create Database",         "value": "google.spanner.admin.database.v1.DatabaseAdmin.CreateDatabase"},
            {"label": "Drop Database",           "value": "google.spanner.admin.database.v1.DatabaseAdmin.DropDatabase"},
        ],
    },
    "Dataflow": {
        "service": "dataflow.googleapis.com",
        "methods": [
            {"label": "Create Job",              "value": "google.dataflow.v1b3.Jobs.CreateJob"},
            {"label": "Update Job",              "value": "google.dataflow.v1b3.Jobs.UpdateJob"},
            {"label": "Cancel Job",              "value": "google.dataflow.v1b3.Jobs.UpdateJob"},  # state=CANCELLED
        ],
    },
    "Cloud Tasks": {
        "service": "cloudtasks.googleapis.com",
        "methods": [
            {"label": "Create Queue",            "value": "google.cloud.tasks.v2.CloudTasks.CreateQueue"},
            {"label": "Delete Queue",            "value": "google.cloud.tasks.v2.CloudTasks.DeleteQueue"},
            {"label": "Create Task",             "value": "google.cloud.tasks.v2.CloudTasks.CreateTask"},
        ],
    },
    "Cloud Scheduler": {
        "service": "cloudscheduler.googleapis.com",
        "methods": [
            {"label": "Create Job",              "value": "google.cloud.scheduler.v1.CloudScheduler.CreateJob"},
            {"label": "Delete Job",              "value": "google.cloud.scheduler.v1.CloudScheduler.DeleteJob"},
            {"label": "Update Job",              "value": "google.cloud.scheduler.v1.CloudScheduler.UpdateJob"},
            {"label": "Run Job",                 "value": "google.cloud.scheduler.v1.CloudScheduler.RunJob"},
        ],
    },
}

# Flat list of provider names for the first dropdown
AUDIT_LOG_PROVIDERS = sorted(AUDIT_LOG_CATALOG.keys())


# ── Param schema helper — provider names only (methods chosen in UI dynamically)
def _build_params_schema() -> list[dict]:
    """
    params_schema for the UI panel.
    The 'method' select options are rendered dynamically by the canvas UI
    based on the chosen provider — the schema here just seeds defaults.
    """
    all_methods_flat = []
    for entry in AUDIT_LOG_CATALOG.values():
        for m in entry["methods"]:
            all_methods_flat.append(m["label"])

    return [
        {
            "key": "name",
            "label": "Trigger Name",
            "type": "text",
            "default": "",
            "placeholder": "my-audit-trigger",
        },
        {
            "key": "provider",
            "label": "Event Provider",
            "type": "select",
            "options": AUDIT_LOG_PROVIDERS,
            "default": AUDIT_LOG_PROVIDERS[0],
            # Signal to UI that changing this field should refresh `method` options
            "cascade_target": "method",
            "catalog": {
                label: [m["label"] for m in entry["methods"]]
                for label, entry in AUDIT_LOG_CATALOG.items()
            },
        },
        {
            "key": "method",
            "label": "Method / Operation",
            "type": "select",
            # Default options for first provider; UI replaces when provider changes
            "options": [m["label"] for m in AUDIT_LOG_CATALOG[AUDIT_LOG_PROVIDERS[0]]["methods"]],
            "default": AUDIT_LOG_CATALOG[AUDIT_LOG_PROVIDERS[0]]["methods"][0]["label"],
            "cascade_parent": "provider",
        },
        {
            "key": "resource_name_filter",
            "label": "Resource Filter (optional)",
            "type": "text",
            "default": "",
            "placeholder": "/projects/_/buckets/my-bucket/objects/*",
        },
        {
            "key": "http_path",
            "label": "Destination Path",
            "type": "text",
            "default": "/",
            "placeholder": "/events/audit",
        },
    ]


@dataclass
class AuditLogTriggerNode(GCPNode):
    """
    Eventarc Trigger via Cloud Audit Logs.

    The user picks:
      - Event Provider  (e.g. "Cloud Storage")
      - Method          (cascading dropdown, auto-filtered by provider)
      - Optional resource path pattern

    Generates:
      type=google.cloud.audit.log.v1.written
      serviceName=<resolved from catalog>
      methodName=<resolved from catalog>
    """

    params_schema: ClassVar = _build_params_schema()

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("triggers", PortType.EVENT, multi=True),
    ]

    node_color:  ClassVar = "#ef4444"   # red — Audit Log
    icon:        ClassVar = "auditLog"
    category:    ClassVar = "Integration_Services"
    description: ClassVar = "Eventarc trigger via Cloud Audit Logs"

    # ── Edge wiring ─────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id and tgt_type == "CloudRunNode":
            ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = list(ctx.get("target_run_ids", []))
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ── Pulumi program ───────────────────────────────────────────────────────

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "")

        target_run_ids = ctx.get("target_run_ids", [])

        def program() -> None:
            trigger_name = props.get("name") or _resource_name(node_dict)

            # ── Resolve provider + method from catalog ───────────────────────
            provider_label = props.get("provider", AUDIT_LOG_PROVIDERS[0])
            catalog_entry  = AUDIT_LOG_CATALOG.get(provider_label)
            if not catalog_entry:
                logger.error(
                    "AuditLogTriggerNode %s: unknown provider '%s'",
                    self.node_id, provider_label,
                )
                return

            service_name = catalog_entry["service"]
            method_label = props.get("method", catalog_entry["methods"][0]["label"])
            method_value = next(
                (m["value"] for m in catalog_entry["methods"] if m["label"] == method_label),
                catalog_entry["methods"][0]["value"],
            )

            resource_filter = props.get("resource_name_filter", "").strip()
            http_path       = props.get("http_path", "/")

            # ── Resolve CloudRun destination ─────────────────────────────────
            first_run_id  = target_run_ids[0] if target_run_ids else ""
            first_run_out = deployed_outputs.get(first_run_id, {})
            cr_name       = first_run_out.get("name", "")

            if not cr_name:
                logger.error(
                    "AuditLogTriggerNode %s: no CloudRunNode destination wired",
                    self.node_id,
                )
                return

            destination = gcp.eventarc.TriggerDestinationArgs(
                cloud_run_service=gcp.eventarc.TriggerDestinationCloudRunServiceArgs(
                    service=cr_name,
                    region=region,
                    path=http_path,
                )
            )

            # ── Matching criteria ────────────────────────────────────────────
            criterias = [
                gcp.eventarc.TriggerMatchingCriteriaArgs(
                    attribute="type",
                    value="google.cloud.audit.log.v1.written",
                ),
                gcp.eventarc.TriggerMatchingCriteriaArgs(
                    attribute="serviceName",
                    value=service_name,
                ),
                gcp.eventarc.TriggerMatchingCriteriaArgs(
                    attribute="methodName",
                    value=method_value,
                ),
            ]
            if resource_filter:
                criterias.append(
                    gcp.eventarc.TriggerMatchingCriteriaArgs(
                        attribute="resourceName",
                        value=resource_filter,
                        operator="match-path-pattern",
                    )
                )

            gcp.eventarc.Trigger(
                self.node_id,
                name=trigger_name,
                location=region,
                project=project,
                service_account=sa_email or None,
                matching_criterias=criterias,
                destination=destination,
            )

            pulumi.export("trigger_name", trigger_name)
            pulumi.export("provider",     provider_label)
            pulumi.export("method",       method_label)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "name":     pulumi_outputs.get("trigger_name", ""),
            "provider": pulumi_outputs.get("provider", ""),
            "method":   pulumi_outputs.get("method", ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("trigger_name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                'resource.type="audited_resource"'
                ' AND resource.labels.service="eventarc.googleapis.com"'
            ),
            project=project,
        )