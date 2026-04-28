"""
nodes/firestore.py — Cloud Firestore resource node (fully self-describing).

Topology
--------
  FirestoreNode ──(FIRESTORE)──► DirectEventTriggerNode   (event source)
  FirestoreNode ──(FIRESTORE)──► WorkflowNode              (visual / step target)
  FirestoreNode ──(FIRESTORE)──► CloudRunNode              (env var: FIRESTORE_DATABASE_<NAME>)

The node can either *create* a Firestore database or act as a *reference* to
an existing one (create_db = False).

Firestore databases are project-scoped singletons in the default case, but
named databases are supported since 2023.

Exports
-------
  database_id   — the Firestore database ID (e.g. "(default)" or "my-db")
  project       — GCP project
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class FirestoreNode(GCPNode):
    """
    Cloud Firestore — NoSQL document database.

    Connect to:
      DirectEventTriggerNode → fire events on document changes
      CloudRunNode           → injects FIRESTORE_DATABASE_<NAME> env var
      WorkflowNode           → visual representation of a Firestore step

    Set create_db=False to reference an existing database (no resource created).
    """

    params_schema: ClassVar = [
        {
            "key": "database_id",
            "label": "Database ID",
            "type": "text",
            "default": "(default)",
            "placeholder": "(default)",
        },
        {
            "key": "location_id",
            "label": "Location",
            "type": "select",
            "options": [
                "europe-west1", "us-central1", "us-east1",
                "asia-east1", "nam5", "eur3",
            ],
            "default": "europe-west1",
        },
        {
            "key": "type",
            "label": "Database Type",
            "type": "select",
            "options": ["FIRESTORE_NATIVE", "DATASTORE_MODE"],
            "default": "FIRESTORE_NATIVE",
        },
        {
            "key": "create_db",
            "label": "Create Database (uncheck to reference existing)",
            "type": "boolean",
            "default": True,
        },
        {
            "key": "deletion_policy",
            "label": "Deletion Policy",
            "type": "select",
            "options": ["DELETE", "ABANDON"],
            "default": "DELETE",
        },
    ]

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
    ]
    outputs: ClassVar = [
        Port("events",    PortType.DIRECT_EVENT, multi=True),  # → DirectEventTriggerNode
        Port("consumers", PortType.FIRESTORE,    multi=True),  # → CloudRunNode / WorkflowNode
    ]

    node_color:  ClassVar = "#ff8c00"
    icon:        ClassVar = "firestore"
    category:    ClassVar = "Storage"
    description: ClassVar = "Cloud Firestore — NoSQL document database"

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id != self.node_id:
            return False

        # FIRESTORE output → CloudRunNode: inject env var
        if tgt_type == "CloudRunNode":
            ctx[tgt_id].setdefault("firestore_ids", []).append(self.node_id)
            return True

        # FIRESTORE output → WorkflowNode: register as a step target
        if tgt_type == "WorkflowNode":
            ctx[tgt_id].setdefault("firestore_ids", []).append(self.node_id)
            return True

        # DIRECT_EVENT output → DirectEventTriggerNode: handled by that node
        # (DirectEventTriggerNode.resolve_edges picks it up on tgt_id == self)
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        create_db  = props.get("create_db", True)
        db_id      = props.get("database_id", "(default)").strip() or "(default)"
        location   = props.get("location_id", "europe-west1")
        db_type    = props.get("type", "FIRESTORE_NATIVE")
        del_policy = props.get("deletion_policy", "DELETE")

        def program() -> None:
            if create_db:
                db = gcp.firestore.Database(
                    self.node_id,
                    name=db_id,
                    location_id=location,
                    type=db_type,
                    project=project,
                    deletion_policy=del_policy,
                )
                pulumi.export("database_id", db.name)
            else:
                # Reference mode — just export the id so downstream nodes
                # can pick it up from deployed_outputs consistently.
                pulumi.export("database_id", db_id)

            pulumi.export("project", project)

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {"database_id": pulumi_outputs.get("database_id", "(default)")}

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        db_id = pulumi_outputs.get("database_id", "")
        if not db_id:
            return None
        return LogSource(
            filter=(
                f'resource.type="datastore_database"'
                f' AND resource.labels.database_id="{db_id}"'
            ),
            project=project,
        )
