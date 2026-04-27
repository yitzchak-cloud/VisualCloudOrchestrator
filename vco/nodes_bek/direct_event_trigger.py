"""
nodes/direct_event_trigger.py — Direct Event Eventarc Trigger Node

Topology
--------
  FirestoreNode        ──(DIRECT_EVENT)──► DirectEventTriggerNode ──(EVENT)──► CloudRunNode
  FirebaseRTDBNode     ──(DIRECT_EVENT)──► DirectEventTriggerNode ──(EVENT)──► CloudRunNode
  CloudBuildNode       ──(DIRECT_EVENT)──► DirectEventTriggerNode ──(EVENT)──► CloudRunNode
  (etc.)

UX Flow (port-driven, then single dropdown):
  1. User wires a source node (e.g. FirestoreNode) into the DIRECT_EVENT input port
  2. The node auto-detects the source type
  3. "Event Type" dropdown shows ONLY the events for that source
  4. If no source is wired, a fallback "Provider" + "Event Type" cascading UI is shown

The key difference from AuditLogTriggerNode:
  - Source is connected via a PHYSICAL PORT (canvas edge), not picked from a list
  - No serviceName/methodName — uses the direct event type string directly
  - Much simpler Pulumi wiring (just matching_criterias with type=<event_type>)
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


# ── Direct Event catalog ───────────────────────────────────────────────────────
# Each provider maps to the node type that connects via port AND its direct events.
# This catalog is used for:
#   a) UI fallback dropdowns when no port is wired
#   b) Validation when a port IS wired (ensures the selected event belongs to source)
DIRECT_EVENT_CATALOG: dict[str, dict] = {
    "Cloud Firestore": {
        "node_type": "FirestoreNode",
        "events": [
            {"label": "Document Created",        "value": "google.cloud.firestore.document.v1.created"},
            {"label": "Document Updated",        "value": "google.cloud.firestore.document.v1.updated"},
            {"label": "Document Deleted",        "value": "google.cloud.firestore.document.v1.deleted"},
            {"label": "Document Written (any)",  "value": "google.cloud.firestore.document.v1.written"},
            {"label": "Document Created (snapshot)", "value": "google.cloud.firestore.document.v1.created.withAuthContext"},
            {"label": "Document Updated (snapshot)", "value": "google.cloud.firestore.document.v1.updated.withAuthContext"},
            {"label": "Document Written (snapshot)", "value": "google.cloud.firestore.document.v1.written.withAuthContext"},
        ],
        # Extra filters required for Firestore (appended as matching_criterias)
        "extra_params": [
            {"key": "database",    "label": "Database ID",    "type": "text", "default": "(default)", "placeholder": "(default)"},
            {"key": "doc_path",    "label": "Document Path",  "type": "text", "default": "",          "placeholder": "collection/{doc}"},
        ],
    },
    "Firebase Realtime Database": {
        "node_type": "FirebaseRTDBNode",
        "events": [
            {"label": "Data Created",            "value": "google.firebase.database.ref.v1.created"},
            {"label": "Data Updated",            "value": "google.firebase.database.ref.v1.updated"},
            {"label": "Data Deleted",            "value": "google.firebase.database.ref.v1.deleted"},
            {"label": "Data Written (any)",      "value": "google.firebase.database.ref.v1.written"},
        ],
        "extra_params": [
            {"key": "instance",  "label": "RTDB Instance", "type": "text", "default": "", "placeholder": "my-db"},
            {"key": "ref_path",  "label": "Ref Path",      "type": "text", "default": "", "placeholder": "/path/to/data"},
        ],
    },
    "Cloud Build": {
        "node_type": "CloudBuildNode",
        "events": [
            {"label": "Build Status Changed",    "value": "google.cloud.build.build.v1.statusChanged"},
        ],
        "extra_params": [],
    },
    "Cloud Storage": {
        "node_type": "GcsBucketNode",
        "events": [
            {"label": "Object Finalized (created)", "value": "google.cloud.storage.object.v1.finalized"},
            {"label": "Object Deleted",          "value": "google.cloud.storage.object.v1.deleted"},
            {"label": "Object Archived",         "value": "google.cloud.storage.object.v1.archived"},
            {"label": "Object Metadata Updated", "value": "google.cloud.storage.object.v1.metadataUpdated"},
        ],
        "extra_params": [
            {"key": "bucket_name", "label": "Bucket Name", "type": "text", "default": "", "placeholder": "my-bucket"},
        ],
    },
    "Firebase Alerts": {
        "node_type": None,  # no dedicated node — fallback UI only
        "events": [
            {"label": "Alert Published",         "value": "google.firebase.firebasealerts.alerts.v1.published"},
        ],
        "extra_params": [
            {"key": "alert_type", "label": "Alert Type", "type": "text", "default": "", "placeholder": "crashlytics.newFatalIssue"},
        ],
    },
    "Firebase Remote Config": {
        "node_type": None,
        "events": [
            {"label": "Config Updated",          "value": "google.firebase.remoteconfig.remoteConfig.v1.updated"},
        ],
        "extra_params": [],
    },
}

DIRECT_EVENT_PROVIDERS = sorted(DIRECT_EVENT_CATALOG.keys())

# Map from node_type string → provider label (for auto-detection on port connect)
_NODE_TYPE_TO_PROVIDER: dict[str, str] = {
    entry["node_type"]: label
    for label, entry in DIRECT_EVENT_CATALOG.items()
    if entry["node_type"]
}


def _build_params_schema() -> list[dict]:
    return [
        {
            "key": "name",
            "label": "Trigger Name",
            "type": "text",
            "default": "",
            "placeholder": "my-direct-trigger",
        },
        {
            "key": "provider",
            "label": "Event Provider",
            "type": "select",
            "options": DIRECT_EVENT_PROVIDERS,
            "default": DIRECT_EVENT_PROVIDERS[0],
            # When a source port IS wired, the UI locks this to the detected provider.
            # When no port is wired, the user picks freely.
            "auto_from_port": True,          # UI hint: lock when port connected
            "cascade_target": "event_type",
            "catalog": {
                label: [e["label"] for e in entry["events"]]
                for label, entry in DIRECT_EVENT_CATALOG.items()
            },
        },
        {
            "key": "event_type",
            "label": "Event Type",
            "type": "select",
            "options": [e["label"] for e in DIRECT_EVENT_CATALOG[DIRECT_EVENT_PROVIDERS[0]]["events"]],
            "default": DIRECT_EVENT_CATALOG[DIRECT_EVENT_PROVIDERS[0]]["events"][0]["label"],
            "cascade_parent": "provider",
        },
        {
            "key": "database",
            "label": "Database ID (Firestore)",
            "type": "text",
            "default": "(default)",
            "placeholder": "(default)",
            "show_if": {"provider": "Cloud Firestore"},
        },
        {
            "key": "doc_path",
            "label": "Document Path (Firestore)",
            "type": "text",
            "default": "",
            "placeholder": "collection/{document=**}",
            "show_if": {"provider": "Cloud Firestore"},
        },
        {
            "key": "instance",
            "label": "RTDB Instance",
            "type": "text",
            "default": "",
            "placeholder": "my-rtdb-instance",
            "show_if": {"provider": "Firebase Realtime Database"},
        },
        {
            "key": "ref_path",
            "label": "Ref Path (RTDB)",
            "type": "text",
            "default": "",
            "placeholder": "/path/to/data",
            "show_if": {"provider": "Firebase Realtime Database"},
        },
        {
            "key": "bucket_name",
            "label": "Bucket Name (GCS)",
            "type": "text",
            "default": "",
            "placeholder": "my-bucket",
            "show_if": {"provider": "Cloud Storage"},
        },
        {
            "key": "http_path",
            "label": "Destination Path",
            "type": "text",
            "default": "/",
            "placeholder": "/events",
        },
    ]


@dataclass
class DirectEventTriggerNode(GCPNode):
    """
    Eventarc Trigger via Direct Events.

    Connect a source node (FirestoreNode, GcsBucketNode, etc.) to the
    DIRECT_EVENT input port — the provider is detected automatically.
    Then pick the specific event type from the filtered dropdown.

    If no port is wired, the user can manually pick Provider + Event Type.
    """

    params_schema: ClassVar = _build_params_schema()

    inputs: ClassVar = [
        Port("source",          PortType.DIRECT_EVENT,   required=False),
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("triggers", PortType.EVENT, multi=True),
    ]

    node_color:  ClassVar = "#8b5cf6"   # purple — Direct Events
    icon:        ClassVar = "directEvent"
    category:    ClassVar = "Integration_Services"
    description: ClassVar = "Eventarc trigger via Direct Events (Firestore, GCS, Firebase, Build…)"

    # ── Edge wiring ──────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # Source node → this trigger (port: DIRECT_EVENT)
        if tgt_id == self.node_id:
            detected = _NODE_TYPE_TO_PROVIDER.get(src_type)
            if detected:
                ctx[self.node_id]["detected_provider"] = detected
                ctx[self.node_id]["source_node_id"]    = src_id
                ctx[self.node_id]["source_node_type"]  = src_type
                return True

        # This trigger → CloudRunNode destination
        if src_id == self.node_id and tgt_type == "CloudRunNode":
            ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
            return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = list(ctx.get("target_run_ids", []))
        if ctx.get("source_node_id"):
            deps.append(ctx["source_node_id"])
        if ctx.get("service_account_id"):
            deps.append(ctx["service_account_id"])
        return deps

    # ── Pulumi program ───────────────────────────────────────────────────────

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        sa_id    = ctx.get("service_account_id", "")
        sa_email = deployed_outputs.get(sa_id, {}).get("email", "")

        target_run_ids    = ctx.get("target_run_ids",    [])
        detected_provider = ctx.get("detected_provider", "")
        source_node_id    = ctx.get("source_node_id",    "")
        source_node_type  = ctx.get("source_node_type",  "")

        def program() -> None:
            trigger_name = props.get("name") or _resource_name(node_dict)
            http_path    = props.get("http_path", "/")

            # ── Resolve provider (port takes priority over dropdown) ──────────
            provider_label = detected_provider or props.get("provider", DIRECT_EVENT_PROVIDERS[0])
            catalog_entry  = DIRECT_EVENT_CATALOG.get(provider_label)
            if not catalog_entry:
                logger.error(
                    "DirectEventTriggerNode %s: unknown provider '%s'",
                    self.node_id, provider_label,
                )
                return

            # ── Resolve event type value from label ──────────────────────────
            event_type_label = props.get("event_type", catalog_entry["events"][0]["label"])
            event_type_value = next(
                (e["value"] for e in catalog_entry["events"] if e["label"] == event_type_label),
                catalog_entry["events"][0]["value"],
            )

            # ── Resolve CloudRun destination ─────────────────────────────────
            first_run_id  = target_run_ids[0] if target_run_ids else ""
            first_run_out = deployed_outputs.get(first_run_id, {})
            cr_name       = first_run_out.get("name", "")

            if not cr_name:
                logger.error(
                    "DirectEventTriggerNode %s: no CloudRunNode destination wired",
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

            # ── Base matching criteria ────────────────────────────────────────
            criterias = [
                gcp.eventarc.TriggerMatchingCriteriaArgs(
                    attribute="type",
                    value=event_type_value,
                )
            ]

            # ── Provider-specific extra filters ───────────────────────────────
            if provider_label == "Cloud Firestore":
                database = props.get("database", "(default)").strip() or "(default)"
                doc_path = props.get("doc_path", "").strip()
                criterias.append(gcp.eventarc.TriggerMatchingCriteriaArgs(
                    attribute="database", value=database,
                ))
                if doc_path:
                    criterias.append(gcp.eventarc.TriggerMatchingCriteriaArgs(
                        attribute="document",
                        value=doc_path,
                        operator="match-path-pattern",
                    ))

            elif provider_label == "Firebase Realtime Database":
                instance = props.get("instance", "").strip()
                ref_path = props.get("ref_path", "").strip()
                if instance:
                    criterias.append(gcp.eventarc.TriggerMatchingCriteriaArgs(
                        attribute="instance", value=instance,
                    ))
                if ref_path:
                    criterias.append(gcp.eventarc.TriggerMatchingCriteriaArgs(
                        attribute="ref",
                        value=ref_path,
                        operator="match-path-pattern",
                    ))

            elif provider_label == "Cloud Storage":
                # Use bucket from wired GcsBucketNode or fallback prop
                bucket_name = (
                    deployed_outputs.get(source_node_id, {}).get("name", "")
                    or props.get("bucket_name", "").strip()
                )
                if bucket_name:
                    criterias.append(gcp.eventarc.TriggerMatchingCriteriaArgs(
                        attribute="bucket", value=bucket_name,
                    ))

            gcp.eventarc.Trigger(
                self.node_id,
                name=trigger_name,
                location=region,
                project=project,
                service_account=sa_email or None,
                matching_criterias=criterias,
                destination=destination,
            )

            pulumi.export("trigger_name",   trigger_name)
            pulumi.export("provider",       provider_label)
            pulumi.export("event_type",     event_type_label)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "name":       pulumi_outputs.get("trigger_name", ""),
            "provider":   pulumi_outputs.get("provider", ""),
            "event_type": pulumi_outputs.get("event_type", ""),
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