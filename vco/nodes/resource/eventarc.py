"""
nodes/eventarc.py — Eventarc Trigger resource node (fully self-describing).

Topology
--------
  PubsubTopicNode  ──(TOPIC)──────► EventarcTriggerNode ──(EVENT)──► CloudRunNode
  GcsBucketNode    ──(STORAGE)────► EventarcTriggerNode ──(EVENT)──► CloudRunNode
  GcsBucketNode    ──(STORAGE)────► EventarcTriggerNode ──(EVENT)──► WorkflowNode  ← NEW
  PubsubTopicNode  ──(TOPIC)──────► EventarcTriggerNode ──(EVENT)──► WorkflowNode  ← NEW

Eventarc trigger types supported
---------------------------------
  pubsub     — fires when a message is published to a wired Pub/Sub topic
  gcs        — fires on GCS object events from a wired GcsBucketNode
               (events: google.cloud.storage.object.v1.finalized | deleted | …)
  direct     — any direct event type string (e.g. AuditLog, custom providers)

The node auto-detects the source type from what is wired:
  • topic wired   → pubsub trigger
  • bucket wired  → gcs trigger
  • neither       → direct/AuditLog (requires event_type param)

Destinations supported:
  • CloudRunNode    — HTTP delivery to a Cloud Run service
  • WorkflowNode    — delivery to a Cloud Workflows workflow  ← NEW
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)

_GCS_EVENTS = [
    "google.cloud.storage.object.v1.finalized",
    "google.cloud.storage.object.v1.deleted",
    "google.cloud.storage.object.v1.archived",
    "google.cloud.storage.object.v1.metadataUpdated",
]


@dataclass
class EventarcTriggerNode(GCPNode):
    """
    Eventarc Trigger — modern event delivery.

    Wire sources:
      PubsubTopicNode → trigger on Pub/Sub message
      GcsBucketNode   → trigger on GCS object event

    Wire destinations:
      EventarcTriggerNode ──(EVENT)──► CloudRunNode   (HTTP delivery)
      EventarcTriggerNode ──(EVENT)──► WorkflowNode   (Workflows delivery)

    Equivalent gcloud (GCS → Workflow):
      gcloud eventarc triggers create image-add-trigger \\
        --location=${WORKFLOW_TRIGGER_REGION} \\
        --destination-workflow=${WORKFLOW_NAME} \\
        --destination-workflow-location=${WORKFLOW_REGION} \\
        --event-filters="type=google.cloud.storage.object.v1.finalized" \\
        --event-filters="bucket=${UPLOAD_BUCKET}" \\
        --service-account="${WORKFLOW_TRIGGER_SA}@${PROJECT}.iam.gserviceaccount.com"
    """

    params_schema: ClassVar = [
        {
            "key": "name", "label": "Trigger Name",
            "type": "text", "default": "", "placeholder": "my-eventarc-trigger",
        },
        {
            "key": "gcs_event_type", "label": "GCS Event Type",
            "type": "select",
            "options": _GCS_EVENTS,
            "default": _GCS_EVENTS[0],
        },
        {
            "key": "direct_event_type", "label": "Direct Event Type (if no source wired)",
            "type": "text", "default": "",
            "placeholder": "google.cloud.audit.log.v1.written",
        },
        {
            "key": "direct_service", "label": "Direct Event Service",
            "type": "text", "default": "",
            "placeholder": "cloudresourcemanager.googleapis.com",
        },
        {
            "key": "http_path", "label": "Destination Path (Cloud Run only)",
            "type": "text", "default": "/", "placeholder": "/events",
        },
        {
            "key": "workflow_region", "label": "Workflow Region (if different from trigger region)",
            "type": "text", "default": "",
            "placeholder": "me-west1",
        },
    ]

    inputs:  ClassVar = [
        Port("topic",           PortType.TOPIC,            required=False),
        Port("bucket",          PortType.STORAGE,          required=False),   # GcsBucketNode → this
        Port("service_account", PortType.SERVICE_ACCOUNT,  required=False),
        Port("iam_binding",     PortType.IAM_BINDING,      required=False, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("triggers",          PortType.EVENT,       multi=True),   # → CloudRunNode
        Port("triggers_workflow", PortType.HTTP_TARGET, multi=True),   # → WorkflowNode
    ]

    node_color:  ClassVar = "#f97316"
    icon:        ClassVar = "eventarc"
    category:    ClassVar = "Integration_Services"
    description: ClassVar = "Modern event delivery — Cloud Run and Workflows"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # Source: PubsubTopicNode → this trigger
        if tgt_id == self.node_id and src_type == "PubsubTopicNode":
            ctx[self.node_id]["topic_source_id"] = src_id
            return True

        # Source: GcsBucketNode → this trigger  (set by GcsBucketNode.resolve_edges)
        # (GcsBucketNode already sets ctx[tgt_id]["bucket_source_id"] = src_id)

        # Destination: this trigger → CloudRunNode
        if src_id == self.node_id and tgt_type == "CloudRunNode":
            ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
            return True

        # Destination: this trigger → WorkflowNode  ← NEW
        if src_id == self.node_id and tgt_type == "WorkflowNode":
            ctx[self.node_id].setdefault("target_workflow_ids", []).append(tgt_id)
            return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        deps: list[str] = list(ctx.get("target_run_ids",      []))
        deps           += list(ctx.get("target_workflow_ids",  []))   # NEW
        if ctx.get("topic_source_id"):
            deps.append(ctx["topic_source_id"])
        if ctx.get("bucket_source_id"):
            deps.append(ctx["bucket_source_id"])
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "")

        topic_source_id    = ctx.get("topic_source_id",    "")
        bucket_source_id   = ctx.get("bucket_source_id",   "")
        target_run_ids     = ctx.get("target_run_ids",     [])
        target_workflow_ids = ctx.get("target_workflow_ids", [])   # NEW

        def _matching_criterias(props, topic_source_id, bucket_source_id, deployed_outputs, project):
            """Build matching_criterias list based on source type."""
            if topic_source_id:
                topic_name = deployed_outputs.get(topic_source_id, {}).get("name", "")
                topic_path = f"projects/{project}/topics/{topic_name}"
                return "pubsub", topic_path, [
                    gcp.eventarc.TriggerMatchingCriteriaArgs(
                        attribute="type",
                        value="google.cloud.pubsub.topic.v1.messagePublished",
                    )
                ]
            elif bucket_source_id:
                bucket_name = deployed_outputs.get(bucket_source_id, {}).get("name", "")
                gcs_event   = props.get("gcs_event_type", _GCS_EVENTS[0])
                return "gcs", None, [
                    gcp.eventarc.TriggerMatchingCriteriaArgs(attribute="type",   value=gcs_event),
                    gcp.eventarc.TriggerMatchingCriteriaArgs(attribute="bucket", value=bucket_name),
                ]
            else:
                event_type = props.get("direct_event_type", "")
                service    = props.get("direct_service", "")
                criterias  = [gcp.eventarc.TriggerMatchingCriteriaArgs(attribute="type", value=event_type)]
                if service:
                    criterias.append(
                        gcp.eventarc.TriggerMatchingCriteriaArgs(attribute="serviceName", value=service)
                    )
                return "direct", None, criterias

        def program() -> None:
            trigger_name = props.get("name") or _resource_name(node_dict)
            http_path    = props.get("http_path", "/")
            wf_region    = props.get("workflow_region", "").strip() or region

            source_type, topic_path, criterias = _matching_criterias(
                props, topic_source_id, bucket_source_id, deployed_outputs, project
            )

            if source_type == "direct" and not props.get("direct_event_type", ""):
                logger.error(
                    "EventarcTriggerNode %s: direct trigger requires 'direct_event_type'",
                    self.node_id,
                )
                return

            # ── Transport block (only for Pub/Sub triggers) ────────────────────
            transport = None
            if source_type == "pubsub" and topic_path:
                transport = gcp.eventarc.TriggerTransportArgs(
                    pubsub=gcp.eventarc.TriggerTransportPubsubArgs(topic=topic_path)
                )

            # ── 1. Cloud Run destinations ──────────────────────────────────────
            for idx, run_id in enumerate(target_run_ids):
                first_run_out = deployed_outputs.get(run_id, {})
                cr_name       = first_run_out.get("name", "")
                if not cr_name:
                    logger.error(
                        "EventarcTriggerNode %s: cannot create trigger without CloudRun name", self.node_id
                    )
                    continue

                destination = gcp.eventarc.TriggerDestinationArgs(
                    cloud_run_service=gcp.eventarc.TriggerDestinationCloudRunServiceArgs(
                        service=cr_name,
                        region=region,
                        path=http_path,
                    )
                )

                suffix = f"-cr{idx}" if len(target_run_ids) > 1 else ""
                gcp.eventarc.Trigger(
                    f"{self.node_id}-cr{idx}" if len(target_run_ids) > 1 else self.node_id,
                    name=f"{trigger_name}{suffix}",
                    location=region,
                    project=project,
                    service_account=sa_email or None,
                    matching_criterias=criterias,
                    transport=transport,
                    destination=destination,
                )
                pulumi.export(f"trigger_name_cr{idx}", f"{trigger_name}{suffix}")

            # ── 2. Workflow destinations ───────────────────────────────────────
            # Equivalent:
            #   gcloud eventarc triggers create image-add-trigger \
            #     --destination-workflow=${WORKFLOW_NAME} \
            #     --destination-workflow-location=${WORKFLOW_REGION} \
            #     --event-filters="type=google.cloud.storage.object.v1.finalized" \
            #     --event-filters="bucket=${UPLOAD_BUCKET}" \
            #     --service-account="${WORKFLOW_TRIGGER_SA}@${PROJECT}.iam.gserviceaccount.com"
            for idx, wf_id in enumerate(target_workflow_ids):
                wf_out  = deployed_outputs.get(wf_id, {})
                wf_name = wf_out.get("workflow_name", "")
                if not wf_name:
                    logger.error(
                        "EventarcTriggerNode %s: cannot create Workflow trigger without workflow_name",
                        self.node_id,
                    )
                    continue

                destination_wf = gcp.eventarc.TriggerDestinationArgs(
                    workflow=f"projects/{project}/locations/{wf_region}/workflows/{wf_name}"
                )

                suffix = f"-wf{idx}" if len(target_workflow_ids) > 1 else "-wf"
                resource_name = (
                    f"{self.node_id}-wf{idx}"
                    if (len(target_workflow_ids) > 1 or len(target_run_ids) > 0)
                    else self.node_id
                )
                gcp.eventarc.Trigger(
                    resource_name,
                    name=f"{trigger_name}{suffix}",
                    location=region,
                    project=project,
                    service_account=sa_email or None,
                    matching_criterias=criterias,
                    transport=transport,
                    destination=destination_wf,
                )
                pulumi.export(f"trigger_name_wf{idx}", f"{trigger_name}{suffix}")

            # Export at least one trigger name for backwards compat
            if not target_run_ids and not target_workflow_ids:
                pulumi.export("trigger_name", trigger_name)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"name": pulumi_outputs.get("trigger_name_cr0", pulumi_outputs.get("trigger_name_wf0", ""))}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        return LogSource(
            filter=(
                'resource.type="audited_resource"'
                ' AND resource.labels.service="eventarc.googleapis.com"'
            ),
            project=project,
        )