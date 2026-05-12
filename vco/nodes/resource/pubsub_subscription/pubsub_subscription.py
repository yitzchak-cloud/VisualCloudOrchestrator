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
from typing import ClassVar, TypedDict

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType
from nodes.ctx_keys import K

from ._pulumi    import make_pulumi_program
from ._terraform import make_terraform_call_vars, terraform_instance_prefix

logger = logging.getLogger(__name__)


# ── ctx TypedDict ─────────────────────────────────────────────────────────────

class PubsubSubCtx(TypedDict, total=False):
    """צורת ה-ctx הייחודית לנוד הזה — total=False כי כל שדה אופציונלי."""
    topic_id:           str        # K.TOPIC_ID       — מ-PubsubTopicNode
    service_account_id: str        # K.SERVICE_ACCOUNT — מ-ServiceAccountNode (push OIDC)
    push_target_ids:    list[str]  # K.PUSH_TARGET_IDS — CR שהסאב דוחף אליו
    consumer_ids:       list[str]  # K.CONSUMER_IDS   — consumers של pull
    receives_from_subs: list[str]  # K.RECEIVES_FROM  — נשמר על היעד


# ── Port definitions ──────────────────────────────────────────────────────────

# Input ports — topic_link is required; oidc_service_account is optional (push only).
# When a ServiceAccountNode is wired to oidc_service_account the OIDC SA email is
# resolved automatically instead of having to be typed manually.
_INPUT_PORTS: list[Port] = [
    Port("topic_link",           PortType.SUBSCRIPTION,    required=True),
]

_PUSH_INPUT_PORTS: list[Port] = [
    Port("topic_link",           PortType.SUBSCRIPTION,    required=True),
    Port("oidc_service_account", PortType.SERVICE_ACCOUNT, required=False),
]

# Output ports differ by type — computed dynamically (see `outputs` property).
_PULL_OUTPUT = [Port("messages", PortType.MESSAGE, multi=True) ]  # many consumers
_PUSH_OUTPUT = [Port("messages", PortType.MESSAGE, multi=False)]  # single CR endpoint


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
    outputs: ClassVar = _PULL_OUTPUT

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
        return _PUSH_OUTPUT if sub_type == "push" else _PULL_OUTPUT
    
    def get_inputs(self) -> list[Port]:
        """
        Returns the correct input ports for the current subscription_type.
        Called by base_node when serialising the live schema for the UI.
        """
        sub_type = self._current_sub_type()
        return _PUSH_INPUT_PORTS if sub_type == "push" else _INPUT_PORTS


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
        nctx: PubsubSubCtx = ctx[self.node_id]

        # ── Subscription is the TARGET (something connects into it) ──────────

        if tgt_id == self.node_id:
            if src_type == "ServiceAccountNode":
                # SA → Sub(push): wire OIDC SA email for push auth
                nctx[K.SERVICE_ACCOUNT] = src_id
                return True
            if src_type == "PubsubTopicNode":
                # Topic → Sub: wire topic reference
                nctx[K.TOPIC_ID] = src_id
                return True

        # ── Subscription is the SOURCE (it connects out to a consumer) ────────

        if src_id == self.node_id:
            if sub_type == "push" and tgt_type == "CloudRunNode":
                # Sub(push) → CR: single push endpoint, resolved from CR uri output
                nctx[K.PUSH_TARGET_IDS] = [tgt_id]
                ctx[tgt_id].setdefault(K.RECEIVES_FROM, []).append(self.node_id)
                print("--------------------------------------------------")
                print(f"Push Sub {self.node_id} → CR {tgt_id}")
                print("--------------------------------------------------")
                return True
            if sub_type == "pull":
                # Sub(pull) → any consumer: multi-consumer fanout
                nctx.setdefault(K.CONSUMER_IDS, []).append(tgt_id)  # type: ignore[misc]
                ctx[tgt_id].setdefault(K.RECEIVES_FROM, []).append(self.node_id)
                return True

        return False

    # ------------------------------------------------------------------
    # DAG dependencies
    # ------------------------------------------------------------------

    def dag_deps(self, ctx) -> list[str]:
        deps = []
        if ctx.get(K.TOPIC_ID):
            deps.append(ctx[K.TOPIC_ID])
        deps.extend(ctx.get(K.PUSH_TARGET_IDS, []))
        if ctx.get(K.SERVICE_ACCOUNT):
            deps.append(ctx[K.SERVICE_ACCOUNT])
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