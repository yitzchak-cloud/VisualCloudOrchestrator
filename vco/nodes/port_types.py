"""
nodes/port_types.py — Port type registry.

Design principle — fewer is better
------------------------------------
A port type defines the *wiring contract* between nodes, not the GCP service.
Two ports that carry the same kind of reference (a storage location, a callable
endpoint, an identity) should share the same type and rely on resolve_edges()
logic inside each node to route correctly.

Port types (current)
---------------------
  SERVICE_ACCOUNT   — identity wire: ServiceAccountNode → any compute node
  NETWORK           — VPC subnetwork wire
  STORAGE           — any storage reference: GCS bucket OR Firestore database
                      The receiving node's resolve_edges() determines behaviour:
                        GcsBucketNode   → env: GCS_BUCKET_<NAME>
                        FirestoreNode   → env: FIRESTORE_DATABASE_<NAME>
  SECRET            — Secret Manager secret reference
  TOPIC             — Pub/Sub topic reference
  DATABASE          — SQL / AlloyDB (reserved for future)
  HTTP_TARGET       — callable HTTPS endpoint (Scheduler/Tasks/Workflows → CR, Functions, Vision)
  TASK_QUEUE        — Cloud Tasks queue reference
  WORKFLOW          — Cloud Workflows (reserved)
  EVENT             — Eventarc → CloudRun delivery
  RUN_JOB           — Scheduler → CloudRunJob trigger
  IAM_BINDING       — IamBindingNode → any resource node (grants roles)
  VISUAL_CONNECTION — canvas-only visual edge (no real GCP resource)

Removed (collapsed into STORAGE)
---------------------------------
  BUCKET        → was used for GcsBucketNode → EventarcTriggerNode; now STORAGE
  FIRESTORE     → was used for FirestoreNode → CloudRunNode/WorkflowNode; now STORAGE
  DIRECT_EVENT  → was used for Firestore → DirectEventTriggerNode; not used in current scope
  MESSAGE       → was used for Pub/Sub message delivery into CloudRun; simplified
  SUBSCRIPTION  → not actively used in any node
  SCHEMA        → not actively used in any node
"""
from enum import Enum


class PortType(Enum):
    SERVICE_ACCOUNT   = "service_account"
    NETWORK           = "network"
    STORAGE           = "storage"       # GCS bucket + Firestore + ArtifactRegistry
    SECRET            = "secret"
    TOPIC             = "topic"
    DATABASE          = "database"      # SQL / AlloyDB (reserved)
    HTTP_TARGET       = "http_target"   # Scheduler / Tasks / Workflows → CR / Functions
    TASK_QUEUE        = "task_queue"    # CloudTasksQueue → consumers
    WORKFLOW          = "workflow"      # reserved
    EVENT             = "event"         # Eventarc trigger → CloudRun
    RUN_JOB           = "run_job"       # Scheduler → CloudRunJob trigger
    IAM_BINDING       = "iam_binding"   # IamBindingNode → any resource node
    VISUAL_CONNECTION = "Visual connection"  # canvas-only, no GCP resource

    # ── Kept for backwards compatibility with any existing node code ──────────
    # These aliases map to their replacement. Remove once all nodes are updated.
    MESSAGE           = "message"       # alias → use STORAGE or TOPIC
    SUBSCRIPTION      = "subscription"  # alias → not used


PORT_META: dict[str, dict] = {
    PortType.SERVICE_ACCOUNT.value:   {"color": "#a78bfa", "label": "SA"},
    PortType.NETWORK.value:           {"color": "#34d399", "label": "Net"},
    PortType.STORAGE.value:           {"color": "#fbbf24", "label": "Storage"},  # GCS + Firestore + AR
    PortType.SECRET.value:            {"color": "#f472b6", "label": "Sec"},
    PortType.TOPIC.value:             {"color": "#60a5fa", "label": "Topic"},
    PortType.SUBSCRIPTION.value:      {"color": "#1523bd", "label": "Sub"},
    PortType.DATABASE.value:          {"color": "#fb923c", "label": "DB"},
    PortType.HTTP_TARGET.value:       {"color": "#38bdf8", "label": "HTTP"},
    PortType.TASK_QUEUE.value:        {"color": "#fb7185", "label": "Queue"},
    PortType.WORKFLOW.value:          {"color": "#c084fc", "label": "WF"},
    PortType.EVENT.value:             {"color": "#f97316", "label": "Event"},
    PortType.RUN_JOB.value:           {"color": "#a5b4fc", "label": "Job"},
    PortType.IAM_BINDING.value:       {"color": "#34d399", "label": "IAM"},
    PortType.VISUAL_CONNECTION.value: {"color": "#9ca3af", "label": "Visual"},
    PortType.MESSAGE.value:           {"color": "#ec4899", "label": "Msg"},
}