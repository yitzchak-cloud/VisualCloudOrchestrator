"""
nodes/eventarc.py — Eventarc Trigger resource node (fully self-describing).

Topology
--------
  PubsubTopicNode  ──(TOPIC)──────► EventarcTriggerNode ──(EVENT)──► CloudRunNode
  GcsBucketNode    ──(BUCKET)─────► EventarcTriggerNode ──(EVENT)──► CloudRunNode

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

The destination is always the wired CloudRunNode.
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

    Wire destination:
      EventarcTriggerNode ──(EVENT)──► CloudRunNode
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
            "key": "http_path", "label": "Destination Path",
            "type": "text", "default": "/", "placeholder": "/events",
        },
    ]

    inputs:  ClassVar = [
        Port("topic",           PortType.TOPIC,          required=False),
        Port("bucket",          PortType.BUCKET,         required=False),
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("triggers", PortType.EVENT, multi=True),
    ]

    node_color:  ClassVar = "#f97316"
    icon:        ClassVar = "eventarc"
    category:    ClassVar = "Integration_Services"
    description: ClassVar = "Modern event delivery"

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
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps: list[str] = list(ctx.get("target_run_ids", []))
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

        topic_source_id  = ctx.get("topic_source_id",  "")
        bucket_source_id = ctx.get("bucket_source_id", "")
        target_run_ids   = ctx.get("target_run_ids",   [])

        def program() -> None:
            trigger_name = props.get("name") or _resource_name(node_dict)
            http_path    = props.get("http_path", "/")

            # ── Resolve destination ────────────────────────────────────────────
            first_run_id  = target_run_ids[0] if target_run_ids else ""
            first_run_out = deployed_outputs.get(first_run_id, {})
            cr_name       = first_run_out.get("name", "")   # short service name
            cr_uri        = first_run_out.get("uri",  "")   # full https:// URI

            destination = gcp.eventarc.TriggerDestinationArgs(
                cloud_run_service=gcp.eventarc.TriggerDestinationCloudRunServiceArgs(
                    service=cr_name,
                    region=region,
                    path=http_path,
                )
            ) if cr_name else None

            if destination is None:
                logger.error("EventarcTriggerNode %s: cannot create trigger without destination", self.node_id)
                return

            # ── Matching conditions by source type ─────────────────────────────
            if topic_source_id:
                # Pub/Sub trigger
                topic_name = deployed_outputs.get(topic_source_id, {}).get("name", "")
                topic_path = f"projects/{project}/topics/{topic_name}"
                gcp.eventarc.Trigger(
                    self.node_id,
                    name=trigger_name,
                    location=region,
                    project=project,
                    service_account=sa_email or None,
                    matching_criterias=[
                        gcp.eventarc.TriggerMatchingCriteriaArgs(
                            attribute="type",
                            value="google.cloud.pubsub.topic.v1.messagePublished",
                        )
                    ],
                    transport=gcp.eventarc.TriggerTransportArgs(
                        pubsub=gcp.eventarc.TriggerTransportPubsubArgs(
                            topic=topic_path,
                        )
                    ),
                    destination=destination,
                )

            elif bucket_source_id:
                # GCS trigger
                bucket_name = deployed_outputs.get(bucket_source_id, {}).get("name", "")
                gcs_event   = props.get("gcs_event_type", _GCS_EVENTS[0])
                gcp.eventarc.Trigger(
                    self.node_id,
                    name=trigger_name,
                    location=region,
                    project=project,
                    service_account=sa_email or None,
                    matching_criterias=[
                        gcp.eventarc.TriggerMatchingCriteriaArgs(
                            attribute="type",
                            value=gcs_event,
                        ),
                        gcp.eventarc.TriggerMatchingCriteriaArgs(
                            attribute="bucket",
                            value=bucket_name,
                        ),
                    ],
                    destination=destination,
                )

            else:
                # Direct / AuditLog trigger
                event_type = props.get("direct_event_type", "")
                service    = props.get("direct_service", "")
                if not event_type:
                    logger.error(
                        "EventarcTriggerNode %s: direct trigger requires 'direct_event_type'",
                        self.node_id,
                    )
                    return
                criterias = [
                    gcp.eventarc.TriggerMatchingCriteriaArgs(attribute="type", value=event_type)
                ]
                if service:
                    criterias.append(
                        gcp.eventarc.TriggerMatchingCriteriaArgs(
                            attribute="serviceName", value=service
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

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"name": pulumi_outputs.get("trigger_name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("trigger_name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="audited_resource"'
                f' AND resource.labels.service="eventarc.googleapis.com"'
            ),
            project=project,
        )