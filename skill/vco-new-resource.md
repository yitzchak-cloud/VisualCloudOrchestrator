---
name: vco-new-resource
description: >
  Step-by-step guide for adding a new GCP resource node to the Visual Cloud Orchestrator (VCO).
  Use this skill whenever the user wants to add a new resource type, create a new node,
  implement a new GCP service node, or understand exactly how existing nodes like
  PubsubSubscriptionNode are structured as the reference implementation.
  This is the authoritative pattern — follow it exactly to ensure the node integrates
  correctly with the UI, deployment engine, Terraform generator, and dynamic schema system.
---

# VCO — Adding a New Resource Node

## Reference Implementation: `PubsubSubscriptionNode`

The most complete and up-to-date node in the project. Use it as the gold standard.
Location: `nodes/resource/pubsub_subscription/`

---

## Directory Structure for a New Node

Create a subdirectory under `nodes/resource/`:

```
nodes/resource/<resource_snake_case>/
├── __init__.py                              # empty or re-export
├── <resource_snake_case>.py                 # Main node class
├── <resource_snake_case>_params.yaml        # params_schema fields
├── _pulumi.py                               # Pulumi program (make_pulumi_program)
├── _terraform.py                            # Terraform (make_terraform_call_vars)
└── terraform/
    ├── main.tf
    ├── variables.tf
    └── outputs.tf
```

The node is **auto-discovered** — no registration step needed. `core/registry.py` walks all submodules and finds every `GCPNode` subclass automatically.

---

## Step 1 — Define the Node Class

File: `nodes/resource/<name>/<name>.py`

```python
"""
nodes/resource/<name>/<name>.py
================================
<ResourceName> — short description.

Topology
--------
  <NodeClass> ──(<PORT_TYPE>)──► <TargetNode>
  <SourceNode> ──(<PORT_TYPE>)──► <NodeClass>

Exports (Pulumi outputs)
------------------------
  name  — resource name
  id    — resource ID
  <other relevant outputs>
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

# Import Pulumi + Terraform delegates (split into separate files for size)
from nodes.resource.<name>._pulumi import make_pulumi_program
from nodes.resource.<name>._terraform import (
    make_terraform_call_vars,
    terraform_instance_prefix as _tf_prefix,
)

logger = logging.getLogger(__name__)


# ── Context key constants ─────────────────────────────────────────────────────
# Use a class to avoid string typos
class K:
    TOPIC_ID       = "topic_id"
    CONSUMER_IDS   = "consumer_ids"
    SERVICE_ACCOUNT = "service_account_id"
    # ... add keys specific to this node's ctx


@dataclass
class <NodeClass>(GCPNode):
    """
    One-line description.
    
    Connect <Source> → this: does X.
    Connect this → <Target>: does Y.
    """

    # params_schema is loaded automatically from the sidecar YAML.
    # Set it to [] if you want to define it inline:
    # params_schema: ClassVar = [{ "key": "name", ... }]

    inputs: ClassVar = [
        Port("topic_link",      PortType.TOPIC,          required=True),   # single-in
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),  # single-in
        Port("iam_binding",     PortType.IAM_BINDING,     required=False, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("messages", PortType.MESSAGE, multi=True),  # output, fans out
    ]

    node_color:  ClassVar = "#f59e0b"                    # hex accent color
    icon:        ClassVar = "cell_tower"                 # maps to icons/<name>/<name>.svg
    category:    ClassVar = "Messaging"                  # sidebar grouping
    description: ClassVar = "Short description shown in sidebar tooltip"

    # ── Dynamic ports (OPTIONAL) ────────────────────────────────────────────────
    # Override get_outputs() / get_inputs() to return ports based on self._props.
    # Must also add triggers_refresh: true to the controlling field in params YAML.
    #
    # def get_outputs(self) -> list[Port]:
    #     if self._props.get("some_field") == "push":
    #         return [Port("endpoint", PortType.HTTP_TARGET)]
    #     return [Port("messages", PortType.MESSAGE, multi=True)]
    #
    # def _current_mode(self) -> str:
    #     return getattr(self, "_props", {}).get("some_field", "default")

    # ── Edge wiring ──────────────────────────────────────────────────────────────

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        """
        Called once per edge during graph resolution.
        Populate ctx[self.node_id] with dependency references.
        Return True if this node handles the edge, False to pass.
        """
        # This node is the TARGET:
        if tgt_id == self.node_id:
            if src_type == "PubsubTopicNode":
                ctx[self.node_id][K.TOPIC_ID] = src_id
                return True
            if src_type == "ServiceAccountNode":
                ctx[self.node_id][K.SERVICE_ACCOUNT] = src_id
                return True

        # This node is the SOURCE:
        if src_id == self.node_id:
            if tgt_type == "CloudRunNode":
                ctx[self.node_id].setdefault(K.CONSUMER_IDS, []).append(tgt_id)
                ctx[tgt_id].setdefault("receives_from", []).append(self.node_id)
                return True

        return False

    # ── DAG dependencies ─────────────────────────────────────────────────────────

    def dag_deps(self, ctx) -> list[str]:
        """
        Return list of node_ids that must be deployed BEFORE this node.
        The orchestrator builds a topological sort from all dag_deps().
        """
        deps = []
        if ctx.get(K.TOPIC_ID):
            deps.append(ctx[K.TOPIC_ID])
        if ctx.get(K.SERVICE_ACCOUNT):
            deps.append(ctx[K.SERVICE_ACCOUNT])
        # push targets must exist so we can read their URI
        deps.extend(ctx.get("push_target_ids", []))
        return deps

    # ── Pulumi program ──────────────────────────────────────────────────────────

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        """
        Return a zero-argument Pulumi program function (closure).
        Called by stack_runner in a thread pool.
        Hydrate self._props here for dynamic port lookups.
        """
        self._props = ctx.get("node", {}).get("props", {})
        return make_pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs)

    # ── Terraform ───────────────────────────────────────────────────────────────

    @property
    def terraform_instance_prefix(self) -> str:
        return _tf_prefix()   # e.g. "ps_sub"

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        self._props = ctx.get("node", {}).get("props", {})
        return make_terraform_call_vars(self, ctx, project, region, all_nodes)

    # ── Live outputs + logging ──────────────────────────────────────────────────

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        """
        Transform raw Pulumi stack outputs to the dict shown in the UI
        Outputs tab. Keys become display labels.
        """
        return {
            "name": pulumi_outputs.get("name", ""),
            "id":   pulumi_outputs.get("id",   ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        """
        Return a Cloud Logging filter string for the node's SSE log stream.
        Return None if this resource doesn't emit logs.
        """
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="pubsub_subscription"'
                f' AND resource.labels.subscription_id="{name}"'
            ),
            project=project,
        )
```

---

## Step 2 — params_schema YAML

File: `nodes/resource/<name>/<name>_params.yaml`

The base class loads this file automatically when `params_schema` is not overridden as a ClassVar.

```yaml
# ── Core ──────────────────────────────────────────────────────────────────────
- key: name
  label: Resource Name
  type: text
  default: ""
  placeholder: my-resource-name
  category: Basic
  description: >
    The unique name of this resource within the project.

- key: region
  label: Region
  type: select
  options: [me-west1, us-central1, us-east1, europe-west1, asia-east1]
  default: me-west1
  category: Basic
  description: >
    GCP region where this resource will be deployed.

# ── Field that changes ports dynamically ──────────────────────────────────────
- key: subscription_type
  label: Subscription Type
  type: select
  options: [pull, push]
  default: pull
  category: Core
  triggers_refresh: true          # ← causes POST /api/node-schema when changed
  description: >
    Changing this switches the available output ports.

# ── Conditional field (only shown when subscription_type == push) ─────────────
- key: push_endpoint
  label: Push Endpoint URL
  type: text
  default: ""
  placeholder: "https://..."
  category: Push Options
  show_if:
    subscription_type: push       # ← hidden unless subscription_type = push
  description: >
    HTTPS URL where Pub/Sub will POST messages.

# ── Checkbox field ─────────────────────────────────────────────────────────────
- key: enable_message_ordering
  label: Message Ordering
  type: checkbox
  default: false
  category: Pull Options
  show_if:
    subscription_type: pull
  description: >
    Deliver messages in order for the same ordering key.

# ── YAML / code editor field ──────────────────────────────────────────────────
- key: source_yaml
  label: Workflow Source YAML
  type: yaml
  default: ""
  category: Advanced
  description: >
    Workflow definition in YAML format. Opens a full CodeMirror editor.
```

### Supported Field Types

| type | UI widget | Notes |
|------|-----------|-------|
| `text` | Text input | Free-form string |
| `number` | Number input | Integer or float |
| `select` | Dropdown | Requires `options: [...]` |
| `checkbox` | Toggle checkbox | Value is `true`/`false` |
| `yaml` | Opens CodeMirror modal | Returns string |
| `code` | Opens CodeMirror modal | Returns string, specify `language:` |
| `json` | Opens CodeMirror modal | Returns string, validates JSON |

### Special Field Flags

| Flag | Effect |
|------|--------|
| `triggers_refresh: true` | UI calls `POST /api/node-schema` on change; server returns updated schema (new ports possible) |
| `show_if: { key: val }` | Field hidden unless `props[key] === val` |
| `required: true` | (on Port, not field) Port shows warning badge if unconnected |
| `auto_from_port: true` | Value auto-set from incoming edge's `detectedProvider` |
| `cascade_parent: key` | `options` loaded from `catalog[props[cascade_parent]]` |

---

## Step 3 — Pulumi Program (_pulumi.py)

File: `nodes/resource/<name>/_pulumi.py`

```python
"""
nodes/resource/<name>/_pulumi.py
=================================
Pulumi program factory for <NodeClass>.
Imported by the main node class.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import _resource_name

if TYPE_CHECKING:
    from nodes.resource.<name>.<name> import <NodeClass>

logger = logging.getLogger(__name__)


def make_pulumi_program(
    node:             "<NodeClass>",
    ctx:              dict[str, Any],
    project:          str,
    region:           str,
    all_nodes:        list[dict],
    deployed_outputs: dict[str, dict],
) -> Callable[[], None]:
    """
    Return a zero-argument function that, when called inside a Pulumi program,
    creates the GCP resource and exports outputs.
    """
    node_dict = ctx.get("node", {})
    props     = node_dict.get("props", {})

    # Read ctx keys populated by resolve_edges()
    topic_id = ctx.get("topic_id", "")
    sa_id    = ctx.get("service_account_id", "")

    # Read outputs from already-deployed dependency nodes
    topic_name = deployed_outputs.get(topic_id, {}).get("name", "")
    sa_email   = deployed_outputs.get(sa_id,    {}).get("email", "")

    # Read user props
    name       = props.get("name") or _resource_name(node_dict)
    ack_secs   = int(props.get("ack_deadline_seconds", 20))
    filter_exp = props.get("filter", "")

    def program() -> None:
        # ── Create the GCP resource ───────────────────────────────────────────
        subscription = gcp.pubsub.Subscription(
            name,
            name=name,
            topic=topic_name,
            project=project,
            ack_deadline_seconds=ack_secs,
            filter=filter_exp or None,
            opts=pulumi.ResourceOptions(delete_before_replace=True),
        )

        # ── Export outputs ────────────────────────────────────────────────────
        pulumi.export("name", subscription.name)
        pulumi.export("id",   subscription.id)

    return program
```

---

## Step 4 — Terraform (_terraform.py)

File: `nodes/resource/<name>/_terraform.py`

```python
"""
nodes/resource/<name>/_terraform.py
=====================================
Terraform call-vars factory for <NodeClass>.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from nodes.base_node import _tf_name

if TYPE_CHECKING:
    from nodes.resource.<name>.<name> import <NodeClass>

logger = logging.getLogger(__name__)


def terraform_instance_prefix(mode: str = "pull") -> str:
    """
    Short prefix for the Terraform module instance name.
    Example: "ps_sub" → module "ps_sub_my_subscription" {}
    """
    return "ps_sub"


def make_terraform_call_vars(
    node:      "<NodeClass>",
    ctx:       dict[str, Any],
    project:   str,
    region:    str,
    all_nodes: list[dict],
) -> dict[str, str]:
    """
    Return a dict of Terraform variable assignments for this node instance.
    Values must be valid HCL literal strings or module references.
    Return {} to skip this node entirely.
    """
    node_dict = ctx.get("node", {})
    props     = node_dict.get("props", {})

    name       = props.get("name") or _tf_name(node_dict)
    topic_name = _resolve_topic_name(ctx, all_nodes)

    if not name:
        logger.warning("Terraform: %s missing name — skipped", node.node_id)
        return {}

    return {
        "name":                f'"{name}"',
        "topic_name":          f'"{topic_name}"',
        "ack_deadline_seconds": str(int(props.get("ack_deadline_seconds", 20))),
        "filter":              f'"{props.get("filter", "")}"',
    }


def _resolve_topic_name(ctx, all_nodes) -> str:
    topic_id = ctx.get("topic_id", "")
    if not topic_id:
        return ""
    for n in all_nodes:
        if n["id"] == topic_id:
            return n.get("props", {}).get("name", "") or ""
    return ""
```

---

## Step 5 — Terraform HCL Module

### `terraform/main.tf`

```hcl
resource "google_pubsub_subscription" "this" {
  name                 = var.name
  topic                = var.topic_name
  project              = var.project_id
  ack_deadline_seconds = var.ack_deadline_seconds
  filter               = var.filter != "" ? var.filter : null
}
```

### `terraform/variables.tf`

```hcl
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "name" {
  description = "Subscription name"
  type        = string
}

variable "topic_name" {
  description = "Parent topic name"
  type        = string
}

variable "ack_deadline_seconds" {
  description = "Ack deadline in seconds"
  type        = number
  default     = 20
}

variable "filter" {
  description = "Subscription filter expression"
  type        = string
  default     = ""
}
```

### `terraform/outputs.tf`

```hcl
output "name" {
  description = "Resource name"
  value       = google_pubsub_subscription.this.name
}

output "id" {
  description = "Resource ID"
  value       = google_pubsub_subscription.this.id
}
```

---

## Step 6 — Add to IamBindingNode (if IAM-bindable)

In `nodes/resource/iam_binding/iam_binding.py`, add to both maps:

```python
_RESOURCE_TYPE_MAP: dict[str, str] = {
    ...
    "<NodeClass>": "<resource_type_key>",   # e.g. "MyResourceNode": "my_resource"
}

_TF_RESOURCE: dict[str, str] = {
    ...
    "<resource_type_key>": "google_<tf_resource>_iam_member",
}
```

And add handling in `_create_resource_iam_member()` for the new resource type.

---

## Complete PubsubSubscriptionNode Example (Actual Reference)

This is the exact node structure in the codebase. Study it carefully.

### Port Definitions

```python
# Pull mode ports (default):
_PULL_OUTPUT = [Port("messages", PortType.MESSAGE, multi=True, label="messages")]
_PUSH_OUTPUT = [Port("push_cr",  PortType.HTTP_TARGET, multi=False, label="push→CR")]

_INPUT_PORTS = [
    Port("topic_link",         PortType.TOPIC,          required=True),
    Port("iam_binding",        PortType.IAM_BINDING,    required=False, multi_in=True),
]
_PUSH_INPUT_PORTS = [
    Port("topic_link",         PortType.TOPIC,          required=True),
    Port("oidc_service_account", PortType.SERVICE_ACCOUNT, required=False),
    Port("iam_binding",        PortType.IAM_BINDING,    required=False, multi_in=True),
]
```

### Dynamic Ports Pattern

```python
def get_outputs(self) -> list[Port]:
    sub_type = self._current_sub_type()
    return _PUSH_OUTPUT if sub_type == "push" else _PULL_OUTPUT

def get_inputs(self) -> list[Port]:
    sub_type = self._current_sub_type()
    return _PUSH_INPUT_PORTS if sub_type == "push" else _INPUT_PORTS

def _current_sub_type(self) -> str:
    props = getattr(self, "_props", {}) or {}
    return props.get("subscription_type", "pull")
```

### params_schema Key Fields

| Key | Type | Description |
|-----|------|-------------|
| `name` | text | Subscription name (3–255 chars) |
| `subscription_type` | select [pull, push] | **triggers_refresh: true** — changes ports |
| `ack_deadline_seconds` | number | 10–600s, default 20 |
| `filter` | text | CEL filter expression |
| `enable_message_ordering` | checkbox | show_if: subscription_type = pull |
| `enable_exactly_once_delivery` | checkbox | show_if: subscription_type = pull |
| `dead_letter_topic` | text | show_if: subscription_type = pull |
| `push_endpoint` | text | show_if: subscription_type = push; auto-filled from wired CR |
| `oidc_service_account_email` | text | show_if: subscription_type = push |
| `audience` | text | show_if: subscription_type = push |

### Edge Wiring Logic

```python
def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
    sub_type = self._current_sub_type()
    nctx = ctx[self.node_id]

    if tgt_id == self.node_id:
        if src_type == "ServiceAccountNode":
            nctx["service_account_id"] = src_id
            return True
        if src_type == "PubsubTopicNode":
            nctx["topic_id"] = src_id
            return True

    if src_id == self.node_id:
        if sub_type == "push" and tgt_type == "CloudRunNode":
            nctx["push_target_ids"] = [tgt_id]
            ctx[tgt_id].setdefault("receives_from", []).append(self.node_id)
            return True
        if sub_type == "pull":
            nctx.setdefault("consumer_ids", []).append(tgt_id)
            ctx[tgt_id].setdefault("receives_from", []).append(self.node_id)
            return True

    return False
```

### Push Pulumi Program

When `subscription_type == "push"`, the Pulumi program auto-resolves the Cloud Run URI from `deployed_outputs`:

```python
push_target_ids = ctx.get("push_target_ids", [])
push_endpoint = props.get("push_endpoint", "").strip()

# Auto-resolve from connected Cloud Run if not manually set
if not push_endpoint and push_target_ids:
    cr_id = push_target_ids[0]
    push_endpoint = deployed_outputs.get(cr_id, {}).get("uri", "")

gcp.pubsub.Subscription(name,
    push_config=gcp.pubsub.SubscriptionPushConfigArgs(
        push_endpoint=push_endpoint,
        oidc_token=gcp.pubsub.SubscriptionPushConfigOidcTokenArgs(
            service_account_email=oidc_email,
        ) if oidc_email else None,
    ),
    ...
)
```

---

## Checklist for a New Resource

- [ ] Create `nodes/resource/<name>/` directory
- [ ] `__init__.py` (empty or re-export)
- [ ] `<name>.py` — GCPNode subclass with all required methods
- [ ] `<name>_params.yaml` — params_schema fields
- [ ] `_pulumi.py` — `make_pulumi_program()` factory
- [ ] `_terraform.py` — `make_terraform_call_vars()` + `terraform_instance_prefix()`
- [ ] `terraform/main.tf` — static HCL resource block
- [ ] `terraform/variables.tf` — all variables used in main.tf
- [ ] `terraform/outputs.tf` — name + id at minimum
- [ ] (Optional) Add to `_RESOURCE_TYPE_MAP` in `iam_binding.py` if IAM-bindable
- [ ] (Optional) Add icon SVG to `icons/<snake_type>/<snake_type>.svg`
- [ ] Verify auto-discovery: restart server and check `GET /api/node-types` includes the new node
- [ ] Test: drag node onto canvas, set props, connect edges, deploy

---

## Helper Functions (from base_node.py)

```python
_resource_name(node_dict) -> str:
    # Returns props["name"] if set, otherwise slugifies node_dict["label"]
    # Use this everywhere instead of hardcoding props["name"]

_tf_name(node_dict) -> str:
    # Terraform-safe name: lowercase, hyphens only
    # Used for module instance naming in main.tf

_node_name(node_dict) -> str:
    # Same as _resource_name

_node_by_id(node_id, all_nodes) -> dict | None:
    # Find a node dict from the flat all_nodes list by id
```
