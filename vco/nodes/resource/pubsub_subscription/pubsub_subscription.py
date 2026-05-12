"""
nodes/resource/pubsub_subscription/pubsub_subscription.py
=========================================================
Unified Pub/Sub Subscription node.

The node presents a single "Subscription" type in the canvas.
The user picks Pull or Push via the `subscription_type` param:

  pull  → output port "messages" is multi=True  (many consumers)
  push  → output port "messages" is multi=False (single CR endpoint)

Dynamic ports
-------------
The `outputs` property is computed at runtime from the current
`subscription_type` prop so that the UI and edge-validation always
reflect the correct cardinality.  The UI reads `schema.outputs` via
the `/api/node-types` endpoint for the palette, but when a node is
hydrated from saved state the live `data.schema` is re-computed server-
side (or patched client-side by the `onPropsChange` hook — see indxe.html).

Parameters are loaded from `subscription_params.yaml` (same directory)
by `GCPNode.__init_subclass__` / `base_node._load_params_yaml()`.

Pulumi logic  → _pulumi.py
Terraform logic → _terraform.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

from ._pulumi    import make_pulumi_program
from ._terraform import make_terraform_call_vars, terraform_instance_prefix

logger = logging.getLogger(__name__)


# ── Port definitions ──────────────────────────────────────────────────────────

# Input port is the same for both subscription types.
_INPUT_PORTS: list[Port] = [
    Port("topic_link", PortType.SUBSCRIPTION, required=True),
]

# Output ports differ by type — computed dynamically (see `outputs` property).
_PULL_OUTPUT = Port("messages", PortType.MESSAGE, multi=True)   # many consumers
_PUSH_OUTPUT = Port("messages", PortType.MESSAGE, multi=False)  # single CR endpoint


# ── Node ──────────────────────────────────────────────────────────────────────

@dataclass
class PubsubSubscriptionNode(GCPNode):
    """
    Unified Pull / Push Pub/Sub Subscription.

    Switch between modes with the `subscription_type` param (pull | push).
    All pull-only and push-only params use `show_if` in the YAML schema
    so the panel stays clean.
    """

    # params_schema is loaded automatically from subscription_params.yaml
    # by base_node._load_params_yaml() — do NOT define it here.

    inputs: ClassVar = _INPUT_PORTS

    # NOTE: `outputs` below is a @property (instance-level) that overrides
    # the ClassVar convention used by other nodes.  We keep a ClassVar
    # fallback for the /api/node-types palette (which instantiates without
    # props), defaulting to pull semantics.
    outputs: ClassVar = [_PULL_OUTPUT]

    node_color:  ClassVar = "#ec485b"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = (
        "Pub/Sub Subscription — Pull (multi-consumer) or Push (single webhook). "
        "Switch type with the Subscription Type param."
    )

    # ------------------------------------------------------------------
    # Dynamic output ports based on current subscription_type prop
    # ------------------------------------------------------------------

    def get_outputs(self) -> list[Port]:
        """
        Returns the correct output ports for the current subscription_type.
        Called by base_node when serialising the live schema for the UI.
        """
        sub_type = self._current_sub_type()
        return [_PUSH_OUTPUT if sub_type == "push" else _PULL_OUTPUT]

    def _current_sub_type(self) -> str:
        """
        Read subscription_type from the node's runtime props if available,
        otherwise fall back to 'pull'.
        """
        # GCPNode stores runtime props in self._props when set by the orchestrator.
        # Fall back gracefully if not yet hydrated.
        props = getattr(self, "_props", {}) or {}
        return props.get("subscription_type", "pull")

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        sub_type = self._current_sub_type()

        if sub_type == "push":
            # Push: record the single target Cloud Run for endpoint resolution
            if src_id == self.node_id and src_type == "PubsubSubscriptionNode":
                ctx[self.node_id].setdefault("push_target_ids", []).append(tgt_id)
                ctx[tgt_id].setdefault("receives_from_subs", []).append(self.node_id)
                return True
        else:
            # Pull: any number of consumers
            if src_id == self.node_id and src_type == "PubsubSubscriptionNode":
                ctx[self.node_id].setdefault("consumer_ids", []).append(tgt_id)
                ctx[tgt_id].setdefault("receives_from_subs", []).append(self.node_id)
                return True

        return False

    # ------------------------------------------------------------------
    # DAG dependencies
    # ------------------------------------------------------------------

    def dag_deps(self, ctx) -> list[str]:
        deps = []
        if ctx.get("topic_id"):
            deps.append(ctx["topic_id"])
        # Push needs the target CR to be deployed first (for its URI)
        deps.extend(ctx.get("push_target_ids", []))
        return deps

    # ------------------------------------------------------------------
    # Pulumi program — delegates to _pulumi.py
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        # Hydrate props so _current_sub_type() works during program build
        self._props = ctx.get("node", {}).get("props", {})
        return make_pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs)

    # ------------------------------------------------------------------
    # Terraform — delegates to _terraform.py
    # ------------------------------------------------------------------

    @property
    def terraform_instance_prefix(self):
        return terraform_instance_prefix(self._current_sub_type())

    def terraform_call_vars(self, ctx, project, region, all_nodes):
        self._props = ctx.get("node", {}).get("props", {})
        return make_terraform_call_vars(self, ctx, project, region, all_nodes)

    # ------------------------------------------------------------------
    # Live outputs & logging
    # ------------------------------------------------------------------

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"subscription_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
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
