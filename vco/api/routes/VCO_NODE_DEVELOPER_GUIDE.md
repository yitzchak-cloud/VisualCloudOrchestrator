# Visual Cloud Orchestrator (VCO) — Developer & Node Reference Guide

> **Purpose:** This document is the single source of truth for building new GCP resource nodes in the VCO system.  
> Every section explains exactly what the engine expects, what currently exists, and how to implement new nodes without touching any engine code.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [How the Engine Works](#2-how-the-engine-works)
3. [The GCPNode Contract — What You Must Implement](#3-the-gcpnode-contract)
4. [Port Types Reference](#4-port-types-reference)
5. [Complete Node Inventory](#5-complete-node-inventory)
6. [Connection Matrix — What Connects to What](#6-connection-matrix)
7. [Context Keys Reference](#7-context-keys-reference)
8. [Pulumi Exports Reference](#8-pulumi-exports-reference)
9. [Worked Example: Adding a New Node](#9-worked-example-adding-a-new-node)
10. [Suggested New Nodes to Implement](#10-suggested-new-nodes-to-implement)
11. [Common Patterns & Recipes](#11-common-patterns--recipes)
12. [Engine Internals (Read-Only Reference)](#12-engine-internals)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Canvas (UI)                        │
│   User drags nodes, draws edges, sets parameters                │
└───────────────────────┬─────────────────────────────────────────┘
                        │ POST /api/deploy  { nodes[], edges[] }
┌───────────────────────▼─────────────────────────────────────────┐
│                    FastAPI Backend                               │
│                                                                  │
│  orchestrator.py                                                 │
│    │                                                             │
│    ├─ graph_resolver.py   resolve_graph()  ←── calls node.resolve_edges()
│    ├─ graph_resolver.py   build_dag()      ←── calls node.dag_deps()
│    ├─ programs.py         build_program()  ←── calls node.pulumi_program()
│    └─ stack_runner.py     run_node_stack() ←── runs Pulumi Automation API
│                                                                  │
│  registry.py   NODE_REGISTRY = { "CloudRunNode": CloudRunNode } │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼ Pulumi Automation API (per-node stack)
               GCP Resources (Cloud Run, Pub/Sub, GCS, …)
```

**Key principle:** The engine is **100% resource-agnostic**. Every piece of resource knowledge lives inside the node class file. Adding a new resource = adding one Python file.

---

## 2. How the Engine Works

### Phase 1 — Graph Resolution (`resolve_graph`)

For every edge `(source → target)` in the canvas, the engine calls `resolve_edges()` on **every registered node**. Nodes inspect the edge and decide if it's theirs to handle. If so, they write information into the `ctx` dict.

`ctx` is a flat dict keyed by `node_id`. Each node gets its own sub-dict:
```python
ctx["CloudRunNode-123"] = {
    "node": <raw node dict from frontend>,
    "subnetwork_id": "SubnetworkNode-456",     # written by SubnetworkNode
    "service_account_id": "SANode-789",        # written by ServiceAccountNode
    "bucket_ids": ["GcsBucketNode-111"],       # written by GcsBucketNode
    "publishes_to_topics": ["TopicNode-222"],  # written by CloudRunNode itself
}
```

### Phase 2 — DAG Build (`build_dag`)

The engine calls `dag_deps(ctx)` on each node. The return value is a list of node IDs that **must be deployed before** this node. Topological sort (Kahn's algorithm) gives the deployment order.

### Phase 3 — Deploy (`build_program` → `run_node_stack`)

For each node in DAG order, the engine calls `pulumi_program(ctx, project, region, all_nodes, deployed_outputs)`. This returns a **Python closure** that, when called, creates Pulumi resources.

`deployed_outputs` accumulates after each node: once `CloudRunNode-123` is deployed, its Pulumi exports (`uri`, `name`, `id`) are available in `deployed_outputs["CloudRunNode-123"]` for subsequent nodes.

---

## 3. The GCPNode Contract

Every node file imports from `nodes.base_node` and subclasses `GCPNode`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, ClassVar
import pulumi
import pulumi_gcp as gcp
from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

@dataclass
class MyNewNode(GCPNode):

    # ── 1. UI Schema ─────────────────────────────────────────────────────────
    params_schema: ClassVar = [
        # Each dict describes one editable field in the canvas property panel
        {
            "key":         "name",          # prop key in node.data.props
            "label":       "Resource Name", # UI label
            "type":        "text",          # text | number | select | boolean | textarea
            "default":     "",
            "placeholder": "my-resource",
            "options":     [],              # only for type=select
        },
    ]

    inputs:  ClassVar[list[Port]] = []   # left-side handles
    outputs: ClassVar[list[Port]] = []   # right-side handles

    node_color:  ClassVar = "#6366f1"    # hex color for the node accent
    icon:        ClassVar = "cloudRun"   # icon name (matches /icons/<name>/<name>.svg)
    category:    ClassVar = "Compute"    # sidebar category
    description: ClassVar = "..."        # tooltip shown in sidebar
    url_field:   ClassVar = None         # prop key to show as clickable URL

    # ── 2. Edge Wiring ────────────────────────────────────────────────────────
    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        """
        Called for EVERY edge in the graph (not just edges involving this node).
        Return True if you handled the edge.
        You can handle edges where:
          - this node is the SOURCE  (src_id == self.node_id)
          - this node is the TARGET  (tgt_id == self.node_id)
          - you need to react as a third party (rare)

        Write your findings into ctx[some_node_id]["some_key"] = value.
        The same edge may be handled by multiple nodes (both sides react).
        """
        return False

    # ── 3. DAG Dependencies ───────────────────────────────────────────────────
    def dag_deps(self, ctx) -> list[str]:
        """
        Return a list of node IDs that MUST be fully deployed before this node.
        Read ctx[self.node_id] for information set during resolve_edges().
        """
        return []

    # ── 4. Pulumi Program ─────────────────────────────────────────────────────
    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        """
        Return a zero-argument closure that calls pulumi_gcp APIs.
        Return None to skip this node (e.g. missing required dependency).

        deployed_outputs[node_id] contains the Pulumi exports of already-deployed nodes.
        Always call pulumi.export() so downstream nodes can read your outputs.
        """
        node_dict = ctx.get("node", {})
        props = node_dict.get("props", {})

        def program() -> None:
            # ... create gcp resources ...
            pulumi.export("name", resource.name)

        return program

    # ── 5. Post-deploy UI sync (optional) ────────────────────────────────────
    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        """
        Map Pulumi exports → canvas node props.
        Called after every successful deploy.
        Return {} to update nothing.
        """
        return {}

    # ── 6. Log streaming (optional) ──────────────────────────────────────────
    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        """
        Return a Cloud Logging filter for the SSE /api/logs/{node_id} endpoint.
        Return None if this resource has no useful log stream.
        """
        return None
```

### The `Port` dataclass

```python
Port(
    name      = "my_port",          # handle ID used by frontend + resolve_edges
    port_type = PortType.HTTP_TARGET, # must match the connecting node's port type
    multi     = False,               # True → output can fan-out to many targets
    required  = False,               # True → UI shows warning badge if unconnected
    multi_in  = False,               # True → input accepts more than one incoming edge
)
```

### The `LogSource` dataclass

```python
LogSource(
    filter    = 'resource.type="cloud_run_revision" AND resource.labels.service_name="my-svc"',
    project   = "",    # filled automatically from stack config
    page_size = 50,
    order     = "desc",
)
```

### Helper functions (from `base_node`)

| Function | Purpose |
|---|---|
| `_resource_name(node_dict)` | Returns `props.name` or slugified label. Use for all GCP resource names. |
| `_node_label(all_nodes, node_id)` | Returns the UI label of any node by ID. |
| `_node_name(all_nodes, node_id)` | Returns the GCP resource name of any node by ID. |

---

## 4. Port Types Reference

All port types are defined in `nodes/port_types.py`. Edges can only connect ports **of the same type**.

| `PortType` enum | Value string | Color | Label | Meaning |
|---|---|---|---|---|
| `SERVICE_ACCOUNT` | `service_account` | `#a78bfa` | SA | IAM service account identity |
| `NETWORK` | `network` | `#34d399` | Net | VPC network / subnetwork reference |
| `STORAGE` | `storage` | `#fbbf24` | GCS | Cloud Storage bucket reference |
| `SECRET` | `secret` | `#f472b6` | Sec | Secret Manager secret reference |
| `TOPIC` | `topic` | `#60a5fa` | Topic | Pub/Sub topic reference |
| `SUBSCRIPTION` | `subscription` | `#1523bd` | Sub | Pub/Sub subscription output from topic |
| `DATABASE` | `database` | `#fb923c` | DB | Database resource reference |
| `SCHEMA` | `schema` | `#8b5cf6` | Schema | Pub/Sub schema reference |
| `MESSAGE` | `message` | `#ec4899` | Msg | Pub/Sub subscription → consumer |
| `HTTP_TARGET` | `http_target` | `#38bdf8` | HTTP | HTTP URL target (Scheduler/Tasks → CR) |
| `TASK_QUEUE` | `task_queue` | `#fb7185` | Queue | Cloud Tasks queue → consumer |
| `WORKFLOW` | `workflow` | `#c084fc` | WF | Workflow orchestration reference |
| `EVENT` | `event` | `#f97316` | Event | Eventarc trigger → Cloud Run |
| `BUCKET` | `bucket` | `#facc15` | Bucket | GCS bucket → Eventarc event source |
| `RUN_JOB` | `run_job` | `#a5b4fc` | Job | Cloud Run Job trigger |

**To add a new port type:** add the enum member to `PortType` and a matching entry in `PORT_META` in `port_types.py`.

---

## 5. Complete Node Inventory

### 5.1 Compute

#### `CloudRunNode` — `nodes/cloud_run.py`
Serverless container runtime (HTTP server).

**Category:** Compute | **Color:** `#6366f1`

**Inputs:**
| Port name | Type | multi_in | required |
|---|---|---|---|
| `service_account` | `SERVICE_ACCOUNT` | no | no |
| `subnet` | `NETWORK` | no | no |
| `http_callers` | `HTTP_TARGET` | **yes** | no |
| `task_queue` | `TASK_QUEUE` | **yes** | no |
| `secret` | `SECRET` | **yes** | no |
| `MESSAGE` | `MESSAGE` | **yes** | no |

**Outputs:**
| Port name | Type | multi |
|---|---|---|
| `publishes_to` | `TOPIC` | **yes** |
| `writes_to` | `STORAGE` | **yes** |

**Props:** `name`, `image`, `memory`, `cpu`, `min_instances`, `max_instances`, `port`, `region`, `service_url`, `vpc_network` (fallback), `vpc_subnetwork` (fallback)

**Pulumi exports:** `uri`, `name`, `id`

**Env vars injected at deploy time:**
- `PUBSUB_TOPIC_<NAME>` — for each wired topic
- `PUBSUB_SUBSCRIPTION_<NAME>` — for each subscription feeding into it
- `GCS_BUCKET_<NAME>` — for each wired bucket
- `CLOUD_TASKS_QUEUE_<NAME>` — for each wired task queue

**ctx keys it reads:** `subnetwork_id`, `service_account_id`, `publishes_to_topics`, `bucket_ids`, `task_queue_ids`, `receives_from_subs`

---

#### `CloudRunJobNode` — `nodes/cloud_run_job.py`
Run-to-completion container job (no HTTP port).

**Category:** Compute | **Color:** `#818cf8`

**Inputs:**
| Port name | Type | multi_in |
|---|---|---|
| `service_account` | `SERVICE_ACCOUNT` | no |
| `subnet` | `NETWORK` | no |
| `triggered_by` | `RUN_JOB` | **yes** |
| `secret` | `SECRET` | **yes** |

**Outputs:**
| Port name | Type |
|---|---|
| `publishes_to` | `TOPIC` |
| `writes_to` | `STORAGE` |

**Props:** `name`, `image`, `memory`, `cpu`, `parallelism`, `task_count`, `max_retries`, `timeout`, `region`, `vpc_network`, `vpc_subnetwork`

**Pulumi exports:** `job_name`, `job_id`

**ctx keys it reads:** `subnetwork_id`, `service_account_id`, `publishes_to_topics`, `bucket_ids`

---

### 5.2 Orchestration

#### `CloudSchedulerNode` — `nodes/cloud_scheduler.py`
Managed cron job (HTTP, Cloud Run Job API, or Pub/Sub delivery).

**Category:** Orchestration | **Color:** `#0ea5e9`

**Inputs:**
| Port name | Type |
|---|---|
| `service_account` | `SERVICE_ACCOUNT` |

**Outputs:**
| Port name | Type | Connects to |
|---|---|---|
| `triggers` | `HTTP_TARGET` | CloudRunNode |
| `triggers_job` | `RUN_JOB` | CloudRunJobNode |
| `publishes_to` | `TOPIC` | PubsubTopicNode |

**Props:** `name`, `schedule` (cron), `timezone`, `http_method`, `http_path`, `http_body`, `pubsub_message`, `retry_count`

**Pulumi exports:** `svc_job_name_<N>`, `svc_target_url_<N>` (per HTTP target), `run_job_scheduler_<N>` (per job), `pubsub_job_name_<N>` (per topic)

**ctx keys it reads:** `target_run_ids`, `target_job_ids`, `target_topic_ids`, `service_account_id`

---

#### `CloudTasksQueueNode` — `nodes/cloud_tasks.py`
Asynchronous task execution queue.

**Category:** Orchestration | **Color:** `#fb7185`

**Inputs:**
| Port name | Type |
|---|---|
| `service_account` | `SERVICE_ACCOUNT` |

**Outputs:**
| Port name | Type | Connects to |
|---|---|---|
| `dispatches_to` | `TASK_QUEUE` | CloudRunNode |

**Props:** `name`, `http_path`, `max_concurrent`, `max_attempts`, `min_backoff`, `max_backoff`, `max_dispatches_per_second`

**Pulumi exports:** `queue_name`, `queue_id`, `handler_url`

**Side effect:** Also writes `task_queue_ids` into the target CloudRunNode's ctx so it gets `CLOUD_TASKS_QUEUE_<NAME>` env var.

---

#### `WorkflowNode` — `nodes/workflows.py`
Cloud Workflows HTTP orchestrator. Auto-generates YAML from wired services.

**Category:** Orchestration | **Color:** `#c084fc`

**Inputs:**
| Port name | Type |
|---|---|
| `service_account` | `SERVICE_ACCOUNT` |

**Outputs:**
| Port name | Type |
|---|---|
| `calls` | `HTTP_TARGET` |

**Props:** `name`, `region`, `source_yaml` (optional override), `http_path`

**Pulumi exports:** `workflow_name`, `workflow_id`

---

### 5.3 Eventing

#### `EventarcTriggerNode` — `nodes/eventarc.py`
Modern event delivery. Auto-detects trigger type from wired source.

**Category:** Eventing | **Color:** `#f97316`

**Inputs:**
| Port name | Type | Source |
|---|---|---|
| `topic` | `TOPIC` | PubsubTopicNode → this |
| `bucket` | `BUCKET` | GcsBucketNode → this |
| `service_account` | `SERVICE_ACCOUNT` | — |

**Outputs:**
| Port name | Type | Target |
|---|---|---|
| `triggers` | `EVENT` | CloudRunNode |

**Props:** `name`, `gcs_event_type` (select), `direct_event_type`, `direct_service`, `http_path`

**Trigger auto-detection:**
- Topic wired → `google.cloud.pubsub.topic.v1.messagePublished`
- Bucket wired → GCS event (configurable)
- Neither → Direct/AuditLog (requires `direct_event_type` param)

**Pulumi exports:** `trigger_name`

---

### 5.4 Messaging

#### `PubsubTopicNode` — `nodes/pubsub.py`
Pub/Sub Topic — the messaging hub.

**Category:** Messaging | **Color:** `#3b82f6`

**Inputs:**
| Port name | Type | Note |
|---|---|---|
| `publishers` | `TOPIC` | Any node can publish (multi_in) |

**Outputs:**
| Port name | Type |
|---|---|
| `subscriptions` | `SUBSCRIPTION` |

**Props:** `name`, `message_retention_duration`, `kms_key_name`

**Pulumi exports:** `name`, `id`

**ctx behavior:** When a subscription connects to this topic, `resolve_edges` writes `ctx[subscription_id]["topic_id"] = self.node_id`.

---

#### `PubsubPullSubscriptionNode` — `nodes/pubsub.py`
Standard pull subscription. Consumer polls for messages.

**Category:** Messaging | **Color:** `#ec485b`

**Inputs:** `topic_link` (`SUBSCRIPTION`, required)

**Outputs:** `messages` (`MESSAGE`, multi)

**Props:** `ack_deadline_seconds`, `filter`, `enable_message_ordering`, `enable_exactly_once_delivery`, `dead_letter_topic`

**Pulumi exports:** `name`, `id`

**ctx behavior:** Writes `ctx[consumer_id]["receives_from_subs"]` for connected CloudRunNodes.

---

#### `PubsubPushSubscriptionNode` — `nodes/pubsub.py`
Push subscription. Pub/Sub delivers to a webhook/service URL.

**Category:** Messaging | **Color:** `#ef4444`

**Inputs:** `topic_link` (`SUBSCRIPTION`, required)

**Outputs:** `messages` (`MESSAGE`, multi)

**Props:** `push_endpoint`, `ack_deadline_seconds`, `oidc_service_account_email`, `audience`, `filter`

**Auto-wiring:** If a `CloudRunNode` is connected on the MESSAGE output, its `uri` is automatically used as the push endpoint.

**Pulumi exports:** `name`, `id`

---

#### `PubsubBigQuerySubscriptionNode` — `nodes/pubsub.py`
Streams Pub/Sub messages directly to a BigQuery table.

**Category:** Messaging | **Color:** `#3b82f6`

**Inputs:** `topic_link` (`SUBSCRIPTION`, required)

**Outputs:** `bq_table` (`DATABASE`)

**Props:** `table` (project.dataset.table), `use_topic_schema`, `write_metadata`

**Pulumi exports:** `name`, `id`

---

#### `PubsubCloudStorageSubscriptionNode` — `nodes/pubsub.py`
Streams Pub/Sub messages to GCS files (Avro or text).

**Category:** Messaging | **Color:** `#eab308`

**Inputs:** `topic_link` (`SUBSCRIPTION`, required)

**Outputs:** `gcs_bucket` (`STORAGE`)

**Props:** `bucket`, `filename_prefix`, `output_format` (avro/text), `max_duration`

**Pulumi exports:** `name`, `id`

---

### 5.5 Storage

#### `GcsBucketNode` — `nodes/gcs_bucket.py`
Cloud Storage Bucket.

**Category:** Storage | **Color:** `#fbbf24`

**Inputs:**
| Port name | Type | Note |
|---|---|---|
| `writers` | `STORAGE` | CR/Workflow → bucket registers them as writers (multi_in) |
| `service_account` | `SERVICE_ACCOUNT` | — |

**Outputs:**
| Port name | Type | Effect |
|---|---|---|
| `storage` | `STORAGE` | → CloudRunNode: injects `GCS_BUCKET_<NAME>` env var |
| `events` | `BUCKET` | → EventarcTriggerNode: sets as event source |

**Props:** `name`, `location`, `storage_class`, `versioning`, `uniform_access`, `lifecycle_age`, `public_access`

**Pulumi exports:** `name`, `url`, `id`

**Side effect:** Grants `roles/storage.objectCreator` to any wired writer's SA.

**ctx keys it writes:**
- `ctx[cloud_run_id]["bucket_ids"]` when STORAGE output is connected to a CloudRunNode
- `ctx[eventarc_id]["bucket_source_id"]` when BUCKET output is connected to Eventarc
- `ctx[self.node_id]["writer_ids"]` when CloudRunNode/WorkflowNode is connected as writer

---

### 5.6 Networking

#### `VpcNetworkNode` — `nodes/network.py`
Reference-only node for a shared-VPC network. Creates NO GCP resource.

**Category:** Networking | **Color:** `#34d399`

**Inputs:** none

**Outputs:** `subnets` (`NETWORK`, multi)

**Props:** `host_project`, `network_name`

**Pulumi exports:** `network_path`, `host_project`, `network_name`

---

#### `SubnetworkNode` — `nodes/network.py`
Reference-only node for a subnetwork. Creates NO GCP resource.

**Category:** Networking | **Color:** `#6ee7b7`

**Inputs:** `network` (`NETWORK`, required) ← VpcNetworkNode

**Outputs:** `cloud_run` (`NETWORK`, multi) → CloudRunNode, CloudRunJobNode

**Props:** `subnetwork_name`, `region`

**Pulumi exports:** `subnetwork_path`, `network_path`, `subnetwork_name`

**Inherits** `host_project` from parent `VpcNetworkNode` via `deployed_outputs`.

---

### 5.7 IAM

#### `ServiceAccountNode` — `nodes/service_account.py`
Create or reference a Service Account.

**Category:** IAM | **Color:** `#a78bfa`

**Inputs:** none

**Outputs:** `service_account` (`SERVICE_ACCOUNT`, multi) → any node that has a `service_account` input

**Props:** `account_id`, `display_name`, `email` (reference mode), `create_sa` (boolean)

**Modes:**
- `create_sa=True` → creates the SA, exports its email
- `create_sa=False` → reference mode, just exports the provided `email`

**Pulumi exports:** `email`, `account_id`, `id`

**ctx behavior:** Writes `ctx[target_id]["service_account_id"] = self.node_id` for every connected node.

---

## 6. Connection Matrix

✅ = supported and implemented | ❌ = not valid | 🔲 = valid but not yet implemented

### Source → Target

| Source ↓ \ Target → | CloudRun | CloudRunJob | PubsubTopic | PubsubPullSub | PubsubPushSub | GcsBucket | EventarcTrigger | CloudScheduler | CloudTasks | Workflow | ServiceAccount | VpcNetwork | Subnetwork |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **ServiceAccountNode** | ✅ SA | ✅ SA | ❌ | ❌ | ❌ | ✅ SA | ✅ SA | ✅ SA | ✅ SA | ✅ SA | ❌ | ❌ | ❌ |
| **VpcNetworkNode** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ NETWORK |
| **SubnetworkNode** | ✅ NETWORK | ✅ NETWORK | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **PubsubTopicNode** | ❌ | ❌ | ❌ | ✅ SUB | ✅ SUB | ❌ | ✅ TOPIC | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **PubsubPullSubNode** | ✅ MESSAGE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **PubsubPushSubNode** | ✅ MESSAGE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **GcsBucketNode** | ✅ STORAGE | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ BUCKET | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **CloudRunNode** | ❌ | ❌ | ✅ TOPIC | ❌ | ❌ | ✅ STORAGE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **CloudRunJobNode** | ❌ | ❌ | ✅ TOPIC | ❌ | ❌ | ✅ STORAGE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **CloudSchedulerNode** | ✅ HTTP_TARGET | ✅ RUN_JOB | ✅ TOPIC | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **CloudTasksQueueNode** | ✅ TASK_QUEUE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **EventarcTriggerNode** | ✅ EVENT | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **WorkflowNode** | ✅ HTTP_TARGET | ❌ | ❌ | ❌ | ❌ | ✅ STORAGE | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 7. Context Keys Reference

These are the `ctx[node_id][key]` values written during `resolve_edges()`. When implementing a new node, use these key names for consistency.

| Key | Written by | Read by | Value type |
|---|---|---|---|
| `service_account_id` | `ServiceAccountNode.resolve_edges` | Any compute node | `str` (node_id) |
| `subnetwork_id` | `SubnetworkNode.resolve_edges` | `CloudRunNode`, `CloudRunJobNode` | `str` (node_id) |
| `vpc_network_id` | `VpcNetworkNode.resolve_edges` | `SubnetworkNode` | `str` (node_id) |
| `topic_id` | `PubsubTopicNode.resolve_edges` | `PubsubPullSubscriptionNode`, `PubsubPushSubscriptionNode`, BQ sub, GCS sub | `str` (node_id) |
| `publisher_ids` | `PubsubTopicNode.resolve_edges` | (informational only) | `list[str]` |
| `publishes_to_topics` | `CloudRunNode.resolve_edges` | `CloudRunNode.dag_deps`, `CloudRunNode.pulumi_program` | `list[str]` (node_ids) |
| `receives_from_subs` | `PubsubPullSubscriptionNode.resolve_edges` | `CloudRunNode.pulumi_program` | `list[str]` (node_ids) |
| `bucket_ids` | `GcsBucketNode.resolve_edges` | `CloudRunNode.pulumi_program` | `list[str]` (node_ids) |
| `writer_ids` | `CloudRunNode.resolve_edges`, `GcsBucketNode.resolve_edges` | `GcsBucketNode.pulumi_program` (IAM grants) | `list[str]` (node_ids) |
| `target_run_ids` | `CloudSchedulerNode`, `CloudTasksQueueNode`, `WorkflowNode`, `EventarcTriggerNode` | each node's `pulumi_program` | `list[str]` (node_ids) |
| `target_job_ids` | `CloudSchedulerNode.resolve_edges` | `CloudSchedulerNode.pulumi_program` | `list[str]` (node_ids) |
| `target_topic_ids` | `CloudSchedulerNode.resolve_edges` | `CloudSchedulerNode.pulumi_program` | `list[str]` (node_ids) |
| `task_queue_ids` | `CloudTasksQueueNode.resolve_edges` | `CloudRunNode.pulumi_program` | `list[str]` (node_ids) |
| `push_target_ids` | `PubsubPushSubscriptionNode.resolve_edges` | `PubsubPushSubscriptionNode.pulumi_program` | `list[str]` (node_ids) |
| `topic_source_id` | `EventarcTriggerNode.resolve_edges` | `EventarcTriggerNode.pulumi_program` | `str` (node_id) |
| `bucket_source_id` | `GcsBucketNode.resolve_edges` | `EventarcTriggerNode.pulumi_program` | `str` (node_id) |
| `consumer_ids` | `PubsubPullSubscriptionNode.resolve_edges` | (informational) | `list[str]` |

---

## 8. Pulumi Exports Reference

After a node is deployed, `deployed_outputs[node_id]` contains these keys:

| Node | Export keys |
|---|---|
| `CloudRunNode` | `uri`, `name`, `id` |
| `CloudRunJobNode` | `job_name`, `job_id` |
| `CloudSchedulerNode` | `svc_job_name_N`, `svc_target_url_N`, `run_job_scheduler_N`, `run_job_target_N`, `pubsub_job_name_N` |
| `CloudTasksQueueNode` | `queue_name`, `queue_id`, `handler_url` |
| `WorkflowNode` | `workflow_name`, `workflow_id` |
| `EventarcTriggerNode` | `trigger_name` |
| `PubsubTopicNode` | `name`, `id` |
| `PubsubPullSubscriptionNode` | `name`, `id` |
| `PubsubPushSubscriptionNode` | `name`, `id` |
| `PubsubBigQuerySubscriptionNode` | `name`, `id` |
| `PubsubCloudStorageSubscriptionNode` | `name`, `id` |
| `GcsBucketNode` | `name`, `url`, `id` |
| `VpcNetworkNode` | `network_path`, `host_project`, `network_name` |
| `SubnetworkNode` | `subnetwork_path`, `network_path`, `subnetwork_name` |
| `ServiceAccountNode` | `email`, `account_id`, `id` |

---

## 9. Worked Example: Adding a New Node

### Goal: `CloudMemorystoreNode` — Redis instance

**File to create:** `nodes/memorystore.py`

```python
"""
nodes/memorystore.py — Cloud Memorystore (Redis) resource node.

Topology
--------
  ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudMemorystoreNode
  SubnetworkNode     ──(NETWORK)──────────► CloudMemorystoreNode
  CloudRunNode reads deployed_outputs["<id>"]["host"] + ["port"]
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar
import pulumi
import pulumi_gcp as gcp
from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType


@dataclass
class CloudMemorystoreNode(GCPNode):

    params_schema: ClassVar = [
        {"key": "name",         "label": "Instance Name",  "type": "text",   "default": "", "placeholder": "my-redis"},
        {"key": "tier",         "label": "Tier",           "type": "select", "options": ["BASIC", "STANDARD_HA"], "default": "BASIC"},
        {"key": "memory_size_gb","label": "Memory (GB)",   "type": "number", "default": 1},
        {"key": "redis_version","label": "Redis Version",  "type": "select", "options": ["REDIS_7_0", "REDIS_6_X"], "default": "REDIS_7_0"},
        {"key": "region",       "label": "Region",         "type": "select", "options": ["me-west1","us-central1","us-east1"], "default": "me-west1"},
    ]

    inputs: ClassVar = [
        Port("subnet",          PortType.NETWORK,          required=False),
        Port("service_account", PortType.SERVICE_ACCOUNT,  required=False),
    ]
    outputs: ClassVar = [
        Port("redis",  PortType.DATABASE, multi=True),  # NEW: add DATABASE to consumers
    ]

    node_color:  ClassVar = "#f97316"
    icon:        ClassVar = "memorystore"
    category:    ClassVar = "Data"
    description: ClassVar = "Managed Redis in-memory database"

    # No edges to resolve (subnet/SA handled by their own nodes writing ctx)
    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # Tell CloudRunNode about this Redis instance so it can get env vars
        if src_id == self.node_id and tgt_type == "CloudRunNode":
            ctx[tgt_id].setdefault("redis_ids", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        deps = []
        if ctx.get("subnetwork_id"):
            deps.append(ctx["subnetwork_id"])
        return deps

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props = node_dict.get("props", {})
        subnet_id = ctx.get("subnetwork_id", "")
        authorized_network = deployed_outputs.get(subnet_id, {}).get("network_path", "")

        def program() -> None:
            inst = gcp.redis.Instance(
                self.node_id,
                name=_resource_name(node_dict),
                tier=props.get("tier", "BASIC"),
                memory_size_gb=int(props.get("memory_size_gb", 1)),
                redis_version=props.get("redis_version", "REDIS_7_0"),
                region=props.get("region", region),
                project=project,
                authorized_network=authorized_network or None,
            )
            pulumi.export("host",          inst.host)
            pulumi.export("port",          inst.port)
            pulumi.export("instance_name", inst.name)
            pulumi.export("id",            inst.id)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "host": pulumi_outputs.get("host", ""),
            "port": str(pulumi_outputs.get("port", "")),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("instance_name", "")
        if not name:
            return None
        return LogSource(
            filter=f'resource.type="redis_instance" AND resource.labels.instance_id="{name}"',
            project=project,
        )
```

**Also update `CloudRunNode.pulumi_program`** (in `cloud_run.py`) to inject `REDIS_HOST_<NAME>` and `REDIS_PORT_<NAME>` env vars by reading `ctx.get("redis_ids", [])` from `deployed_outputs`.

**That's it.** The registry auto-discovers the new class and the engine handles the rest.

---

## 10. Suggested New Nodes to Implement

The following nodes are commonly needed in GCP architectures and fit the existing port type system cleanly.

### 10.1 `CloudSQLNode` — `nodes/cloud_sql.py`
Managed relational database (PostgreSQL / MySQL / SQL Server).

**Category:** Data | **Suggested color:** `#fb923c`

**Ports:**
- Input: `service_account` (SA), `subnet` (NETWORK)
- Output: `database` (DATABASE) → CloudRunNode

**Key props:** `database_version`, `tier`, `region`, `disk_size_gb`, `ha` (boolean)

**Pulumi exports:** `connection_name`, `private_ip_address`, `name`, `id`

**Env vars to inject into CloudRunNode:**
- `CLOUDSQL_CONNECTION_<NAME>` = connection name
- `CLOUDSQL_HOST_<NAME>` = private IP

**DAG deps:** SubnetworkNode (VPC peering required for private IP)

**Pulumi resource:** `gcp.sql.DatabaseInstance`

---

### 10.2 `SecretManagerNode` — `nodes/secret_manager.py`
Managed secrets. Grants Cloud Run SA access to the secret.

**Category:** Security | **Suggested color:** `#f472b6`

**Ports:**
- Input: none
- Output: `secret` (SECRET) → CloudRunNode (multi)

**Key props:** `name`, `replication` (automatic/user-managed), `rotation_days`

**Pulumi exports:** `name`, `secret_id`, `id`

**resolve_edges behavior:**
- When `src_type == "SecretManagerNode"` and `tgt_type == "CloudRunNode"`:
  - Write `ctx[tgt_id].setdefault("secret_ids", []).append(self.node_id)`
- CloudRunNode then mounts secrets via `gcp.cloudrunv2.ServiceTemplateContainerEnvArgs` using `value_source`

**Pulumi resource:** `gcp.secretmanager.Secret`

---

### 10.3 `BigQueryDatasetNode` — `nodes/bigquery.py`
BigQuery dataset + optional table schema.

**Category:** Data | **Suggested color:** `#3b82f6`

**Ports:**
- Input: `writers` (STORAGE) — CloudRun/Workflow writing data
- Output: `dataset` (DATABASE) → CloudRunNode, PubsubBigQuerySubscription

**Key props:** `dataset_id`, `location`, `description`, `default_table_expiration_ms`

**Pulumi exports:** `dataset_id`, `self_link`, `id`

**Env vars to inject:** `BIGQUERY_DATASET_<NAME>`

**Pulumi resources:** `gcp.bigquery.Dataset`, optional `gcp.bigquery.DatasetIamBinding`

---

### 10.4 `FirestoreNode` — `nodes/firestore.py`
Firestore database (Native or Datastore compat mode).

**Category:** Data | **Suggested color:** `#f97316`

**Ports:**
- Input: `service_account` (SA)
- Output: `database` (DATABASE) → CloudRunNode

**Key props:** `mode`, `location`, `ttl_field`

**Pulumi exports:** `name`, `id`

**Env vars to inject:** `FIRESTORE_DATABASE_<NAME>` (usually `(default)`)

**Pulumi resource:** `gcp.firestore.Database`

---

### 10.5 `CloudMemorystoreNode` — `nodes/memorystore.py`
(Full implementation shown in Section 9 above)

**Category:** Data | **Color:** `#f97316`

**Ports:** `subnet` (NETWORK), `service_account` (SA) inputs; `redis` (DATABASE) output

**Pulumi resource:** `gcp.redis.Instance`

---

### 10.6 `ArtifactRegistryNode` — `nodes/artifact_registry.py`
Container image registry (replaces Container Registry).

**Category:** Storage | **Suggested color:** `#818cf8`

**Ports:**
- Input: `service_account` (SA)
- Output: `registry` (STORAGE) → CloudRunNode (enables image push/pull access)

**Key props:** `name`, `format` (DOCKER/MAVEN/NPM/…), `location`, `description`

**Pulumi exports:** `repository_id`, `uri` (e.g. `me-west1-docker.pkg.dev/project/name`), `id`

**Side effect:** Grants `roles/artifactregistry.reader` to wired CloudRun's SA

**Env vars to inject:** `ARTIFACT_REGISTRY_URI_<NAME>`

**Pulumi resource:** `gcp.artifactregistry.Repository`

---

### 10.7 `LoadBalancerNode` — `nodes/load_balancer.py`
Global HTTP(S) load balancer with URL map.

**Category:** Networking | **Suggested color:** `#06b6d4`

**Ports:**
- Input: `backends` (HTTP_TARGET) — CloudRunNode as backend
- Output: `frontend` (HTTP_TARGET) — external URL

**Key props:** `name`, `ssl_cert` (managed cert domain), `cdn_enabled`, `type` (EXTERNAL/INTERNAL)

**Pulumi exports:** `ip_address`, `url`, `ssl_cert_name`, `id`

**Pulumi resources:** `gcp.compute.GlobalAddress`, `gcp.compute.ManagedSslCertificate`, `gcp.compute.TargetHttpsProxy`, `gcp.compute.UrlMap`, `gcp.compute.GlobalForwardingRule`, `gcp.compute.BackendService`, `gcp.compute.RegionNetworkEndpointGroup`

---

### 10.8 `CloudArmorNode` — `nodes/cloud_armor.py`
WAF security policy (attaches to Load Balancer).

**Category:** Security | **Suggested color:** `#ef4444`

**Ports:**
- Output: `security_policy` — attach to LoadBalancerNode

**Key props:** `name`, `default_action` (allow/deny), rules list

**Pulumi exports:** `policy_name`, `self_link`

**Pulumi resource:** `gcp.compute.SecurityPolicy`

---

### 10.9 `VpcConnectorNode` — `nodes/vpc_connector.py`
Serverless VPC Access connector (for Cloud Run private network egress without shared-VPC).

**Category:** Networking | **Suggested color:** `#34d399`

**Ports:**
- Input: `network` (NETWORK)
- Output: `connector` (NETWORK) → CloudRunNode

**Key props:** `name`, `ip_cidr_range`, `min_throughput`, `max_throughput`

**Pulumi exports:** `connector_id`, `self_link`

**Pulumi resource:** `gcp.vpcaccess.Connector`

---

### 10.10 `CloudRunV2JobTriggerNode` — extend existing Scheduler
(Already covered by `CloudSchedulerNode` → `CloudRunJobNode` via `RUN_JOB` port)

---

### 10.11 `PubSubSchemaNode` — `nodes/pubsub_schema.py`
Pub/Sub message schema (Avro or Protocol Buffer).

**Category:** Messaging | **Suggested color:** `#8b5cf6`

**Ports:**
- Output: `schema` (SCHEMA) → PubsubTopicNode

**Key props:** `name`, `type` (AVRO/PROTOCOL_BUFFER), `definition` (JSON/proto text)

**Pulumi exports:** `name`, `id`

**resolve_edges:** writes `ctx[topic_id]["schema_id"] = self.node_id`

**PubsubTopicNode must be updated** to read `schema_id` and pass `schema_settings` to `gcp.pubsub.Topic`.

**Pulumi resource:** `gcp.pubsub.Schema`

---

### 10.12 `CloudBuildTriggerNode` — `nodes/cloud_build.py`
CI/CD build trigger from source repo or Pub/Sub.

**Category:** Orchestration | **Suggested color:** `#f59e0b`

**Ports:**
- Input: `topic` (TOPIC) — trigger on Pub/Sub
- Output: `artifacts` (STORAGE) — writes to GCS/Artifact Registry

**Key props:** `name`, `filename` (cloudbuild.yaml path), `branch_pattern`, `repo_name`

**Pulumi resource:** `gcp.cloudbuild.Trigger`

---

## 11. Common Patterns & Recipes

### Pattern A: Basic Event-Driven Pipeline
```
CloudSchedulerNode
    │  (HTTP_TARGET)
    ▼
CloudRunNode  ──(TOPIC)──► PubsubTopicNode
                                │  (SUBSCRIPTION)
                                ▼
                    PubsubPullSubscriptionNode
                                │  (MESSAGE)
                                ▼
                    CloudRunNode (consumer)
```

**How the engine handles this:**
1. `CloudSchedulerNode.resolve_edges` → writes `target_run_ids` on Scheduler's ctx
2. `CloudRunNode.resolve_edges` (producer) → writes `publishes_to_topics` on producer's ctx
3. `PubsubTopicNode.resolve_edges` → writes `topic_id` on subscription's ctx
4. `PubsubPullSubscriptionNode.resolve_edges` → writes `receives_from_subs` on consumer CR's ctx
5. DAG order: Scheduler → Topic → Pull Sub → Consumer CR → Producer CR (Producer CR depends on Topic)

---

### Pattern B: GCS-Triggered Processing
```
GcsBucketNode ──(BUCKET)──► EventarcTriggerNode ──(EVENT)──► CloudRunNode
```

**ctx flow:**
1. `GcsBucketNode.resolve_edges` → `ctx[eventarc_id]["bucket_source_id"] = bucket_id`
2. `EventarcTriggerNode.resolve_edges` → `ctx[eventarc_id]["target_run_ids"] = [cr_id]`
3. DAG: GcsBucketNode → CloudRunNode → EventarcTriggerNode

---

### Pattern C: Async Task Queue
```
CloudRunNode (enqueuer) ──(???)──► CloudTasksQueueNode ──(TASK_QUEUE)──► CloudRunNode (handler)
```

> Note: The enqueuer does not need an explicit edge — it reads `CLOUD_TASKS_QUEUE_<NAME>` env var.

**Setup:** Draw only `CloudTasksQueueNode → handler CloudRunNode`. The queue name env var is automatically injected into the handler.

---

### Pattern D: Shared-VPC Cloud Run
```
VpcNetworkNode ──(NETWORK)──► SubnetworkNode ──(NETWORK)──► CloudRunNode
ServiceAccountNode ──(SERVICE_ACCOUNT)──► CloudRunNode
```

**ctx flow:**
1. `VpcNetworkNode.resolve_edges` → `ctx[subnet_id]["vpc_network_id"] = network_id`
2. `SubnetworkNode.resolve_edges` → `ctx[cr_id]["subnetwork_id"] = subnet_id`
3. `ServiceAccountNode.resolve_edges` → `ctx[cr_id]["service_account_id"] = sa_id`
4. DAG: VpcNetworkNode → SubnetworkNode → CloudRunNode (SA deploys in parallel)
5. CloudRunNode reads both `network_path` and `subnetwork_path` from `deployed_outputs`

---

### Pattern E: Cloud Run Job with Schedule
```
ServiceAccountNode ──(SA)──► CloudRunJobNode ◄──(RUN_JOB)── CloudSchedulerNode ──(SA)──► ServiceAccountNode
        └──(SA)──► CloudSchedulerNode (same or different SA)
```

The scheduler calls the Cloud Run Jobs execution API at the cron schedule.

---

## 12. Engine Internals

> This section is for reference only. You do not need to modify these files when adding new nodes.

### `nodes/registry.py`
Auto-discovers all `GCPNode` subclasses by walking the `nodes` package. Import `NODE_REGISTRY` to get `dict[str, type]`.

```python
from core.registry import NODE_REGISTRY
# NODE_REGISTRY["CloudRunNode"] == CloudRunNode
```

### `deploy/graph_resolver.py`
- `resolve_graph(nodes, edges, node_registry)` → `ctx` dict
- `build_dag(nodes, ctx, node_registry)` → ordered `list[node_id]`

### `deploy/programs.py`
- `build_program(node, ntype, nc, project, region, all_nodes, deployed_outputs, node_registry)` → closure or None

### `deploy/stack_runner.py`
- `run_node_stack(node_id, program, stack_name, work_dir, project, region, on_output, ...)` → `dict` of outputs
- Each node gets its own Pulumi stack: `dev-<safe_node_id>` in `work_dir/<safe_node_id>/`
- Preview is run first; `up()` is skipped if there are no changes

### `deploy/state_reader.py`
- `read_actual_state(work_dir, stack)` → `{"node_ids": [...], "nodes": {...}, "stale_dirs": [...]}`
- Determines which nodes are "actually deployed" by checking Pulumi stack history + outputs

### `deploy/pulumi_helpers.py`
- `_destroy_node_stack(...)` — destroys a specific node's stack and removes its directory
- `_resource_name(node_dict)` — returns a valid GCP resource name from a node dict

### `core/log_bridge.py`
Sentinel signals emitted by orchestrator → WS events:
- `__node_working__` → `broadcast_node_working(node_id)`
- `__node_deployed__` → `broadcast_node_status(node_id, "deployed")`
- `__node_failed__` → `broadcast_node_status(node_id, "failed")`
- `__node_no_change__` → `broadcast_node_status(node_id, "no_change")`

### `core/ws_manager.py`
WebSocket event types sent to frontend:
| Event | Payload fields |
|---|---|
| `deploy_started` | `total, create, update, destroy, touched_ids` |
| `node_working` | `node_id` |
| `node_status` | `node_id, status, action?` |
| `log` | `msg, level, node_id?` |
| `deploy_outputs` | `outputs` (flat dict) |
| `deploy_complete` | `changed, failed` |
| `graph_saved` | `node_count` |
| `node_props_update` | `node_id, props` |

---

## Checklist: Adding a New Node

- [ ] Create `nodes/<my_node>.py`
- [ ] Subclass `GCPNode` with `@dataclass`
- [ ] Define `params_schema` with all editable props
- [ ] Define `inputs` and `outputs` using existing `PortType` values (or add new ones to `port_types.py`)
- [ ] Set `node_color`, `icon`, `category`, `description`
- [ ] Implement `resolve_edges` — write to `ctx[some_node_id]["some_key"]`
- [ ] Implement `dag_deps` — return list of node_ids this node depends on
- [ ] Implement `pulumi_program` — return a closure that creates GCP resources
- [ ] Call `pulumi.export("key", value)` for every output downstream nodes need
- [ ] Implement `live_outputs` — map exports to canvas props
- [ ] Implement `log_source` — return Cloud Logging filter or `None`
- [ ] If wiring to `CloudRunNode`, update `CloudRunNode.pulumi_program` to inject env vars from `ctx.get("my_key_ids", [])`
- [ ] Add an icon SVG at `icons/<icon_name>/<icon_name>.svg` (optional, falls back to inline)
- [ ] **No changes needed** to engine files (`graph_resolver.py`, `programs.py`, `stack_runner.py`, `registry.py`, `orchestrator.py`)
