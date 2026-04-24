# """
# nodes/nodes.py — Compute, Data, Storage, Security, Networking nodes (fully self-describing).
# """
# from __future__ import annotations

# import logging
# import re
# from dataclasses import dataclass, field
# from typing import Any, Callable, ClassVar

# import pulumi
# import pulumi_gcp as gcp

# from nodes.base_node import GCPNode, LogSource, Port
# from nodes.port_types import PortType

# logger = logging.getLogger(__name__)







# # ── Cloud Function ────────────────────────────────────────────────────────────

# @dataclass
# class CloudFunctionNode(GCPNode):
#     runtime:     str = "python311"
#     entry_point: str = "main"
#     memory:      str = "256Mi"
#     timeout:     int = 60
#     trigger:     str = "http"

#     inputs: ClassVar = [
#         Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
#         Port("trigger_topic",   PortType.TOPIC),
#         Port("secret",          PortType.SECRET, multi=True, multi_in=True),
#     ]
#     outputs: ClassVar = [
#         Port("publishes_to",    PortType.TOPIC,   multi=True),
#         Port("writes_to",       PortType.STORAGE, multi=True),
#     ]
#     node_color:  ClassVar = "#a78bfa"
#     icon:        ClassVar = "cloudFunctions"
#     category:    ClassVar = "Compute"
#     description: ClassVar = "Event-driven serverless function"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("CloudFunctionNode: pulumi_program not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {"function_url": pulumi_outputs.get("uri", "")}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         name = pulumi_outputs.get("name", "")
#         if not name:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="cloud_function"'
#                 f' AND resource.labels.function_name="{name}"'
#                 f' AND resource.labels.region="{region}"'
#             ),
#             project=project,
#         )


# # ── Cloud SQL ─────────────────────────────────────────────────────────────────

# @dataclass
# class CloudSQLNode(GCPNode):
#     tier:             str  = "db-f1-micro"
#     database_version: str  = "POSTGRES_15"
#     region:           str  = "us-central1"
#     disk_size_gb:     int  = 10
#     ha:               bool = False

#     inputs: ClassVar = [
#         Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
#         Port("network",         PortType.NETWORK,         required=True),
#     ]
#     outputs: ClassVar = [Port("connection", PortType.DATABASE, multi=True)]
#     node_color:  ClassVar = "#f97316"
#     icon:        ClassVar = "cloudSql"
#     category:    ClassVar = "Data"
#     description: ClassVar = "Managed relational database"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("CloudSQLNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {"connection_name": pulumi_outputs.get("connection_name", "")}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         name = pulumi_outputs.get("name", "")
#         if not name:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="cloudsql_database"'
#                 f' AND resource.labels.database_id="{project}:{name}"'
#             ),
#             project=project,
#         )


# # ── BigQuery ──────────────────────────────────────────────────────────────────

# @dataclass
# class BigQueryNode(GCPNode):
#     location:      str = "US"
#     dataset_id:    str = ""
#     partition_by:  str = ""
#     expiration_ms: int = 0

#     inputs: ClassVar = [
#         Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
#         Port("writes_in",       PortType.STORAGE,         multi_in=True),
#     ]
#     outputs: ClassVar = [Port("query_out", PortType.DATABASE, multi=True)]
#     node_color:  ClassVar = "#3b82f6"
#     icon:        ClassVar = "bigquery"
#     category:    ClassVar = "Data"
#     description: ClassVar = "Serverless data warehouse"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("BigQueryNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         dataset = pulumi_outputs.get("dataset_id", "")
#         if not dataset:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="bigquery_dataset"'
#                 f' AND resource.labels.dataset_id="{dataset}"'
#             ),
#             project=project,
#         )


# # ── Firestore ─────────────────────────────────────────────────────────────────

# @dataclass
# class FirestoreNode(GCPNode):
#     mode:      str = "NATIVE"
#     location:  str = "us-central"
#     ttl_field: str = ""

#     inputs:  ClassVar = [Port("service_account", PortType.SERVICE_ACCOUNT, required=True)]
#     outputs: ClassVar = [Port("document_ref",    PortType.DATABASE,         multi=True)]
#     node_color:  ClassVar = "#f59e0b"
#     icon:        ClassVar = "firestore"
#     category:    ClassVar = "Data"
#     description: ClassVar = "Serverless NoSQL document DB"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("FirestoreNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         return LogSource(
#             filter=f'resource.type="datastore_database" AND resource.labels.project_id="{project}"',
#             project=project,
#         )


# # ── Memorystore ───────────────────────────────────────────────────────────────

# @dataclass
# class MemorystoreNode(GCPNode):
#     tier:           str = "BASIC"
#     memory_size_gb: int = 1
#     redis_version:  str = "REDIS_7_0"
#     region:         str = "us-central1"

#     inputs: ClassVar = [
#         Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
#         Port("network",         PortType.NETWORK,         required=True),
#     ]
#     outputs: ClassVar = [Port("cache_endpoint", PortType.DATABASE, multi=True)]
#     node_color:  ClassVar = "#ef4444"
#     icon:        ClassVar = "memorystore"
#     category:    ClassVar = "Data"
#     description: ClassVar = "Managed Redis / Memcached"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("MemorystoreNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {"host": pulumi_outputs.get("host", "")}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         name = pulumi_outputs.get("name", "")
#         if not name:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="redis_instance"'
#                 f' AND resource.labels.instance_id="{name}"'
#             ),
#             project=project,
#         )


# # ── GCS Bucket ────────────────────────────────────────────────────────────────

# @dataclass
# class GCSBucketNode(GCPNode):
#     location:       str  = "US"
#     storage_class:  str  = "STANDARD"
#     versioning:     bool = False
#     public_access:  bool = False
#     lifecycle_days: int  = 0

#     inputs: ClassVar = [
#         Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
#         Port("bucket",          PortType.STORAGE,         multi=True),
#     ]
#     node_color:  ClassVar = "#eab308"
#     icon:        ClassVar = "cloudStorage"
#     category:    ClassVar = "Storage"
#     description: ClassVar = "Object storage bucket"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("GCSBucketNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {"bucket_url": f"gs://{pulumi_outputs.get('name', '')}"}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         name = pulumi_outputs.get("name", "")
#         if not name:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="gcs_bucket"'
#                 f' AND resource.labels.bucket_name="{name}"'
#             ),
#             project=project,
#         )


# # ── Secret Manager ────────────────────────────────────────────────────────────

# @dataclass
# class SecretManagerNode(GCPNode):
#     replication:   str = "automatic"
#     rotation_days: int = 0

#     inputs:  ClassVar = [Port("service_account", PortType.SERVICE_ACCOUNT, required=True)]
#     outputs: ClassVar = [Port("secret_ref",      PortType.SECRET,          multi=True)]
#     node_color:  ClassVar = "#ec4899"
#     icon:        ClassVar = "secretManager"
#     category:    ClassVar = "Security"
#     description: ClassVar = "Encrypted secrets store"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("SecretManagerNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         name = pulumi_outputs.get("name", "")
#         if not name:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="secretmanager.googleapis.com/Secret"'
#                 f' AND resource.labels.secret_id="{name}"'
#             ),
#             project=project,
#         )



# # ── Load Balancer ─────────────────────────────────────────────────────────────

# @dataclass
# class LoadBalancerNode(GCPNode):
#     lb_type:     str  = "EXTERNAL"
#     protocol:    str  = "HTTPS"
#     ssl_cert:    str  = ""
#     cdn_enabled: bool = False

#     inputs: ClassVar = [
#         Port("network",     PortType.NETWORK, required=True),
#         Port("backend",     PortType.NETWORK, multi_in=True),
#     ]
#     outputs: ClassVar = [Port("frontend_ip", PortType.NETWORK, multi=True)]
#     node_color:  ClassVar = "#06b6d4"
#     icon:        ClassVar = "cloudLoadBalancing"
#     category:    ClassVar = "LoadBalancer"
#     description: ClassVar = "HTTP(S) / TCP / UDP load balancer"

#     def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
#         return False

#     def dag_deps(self, ctx) -> list[str]:
#         return []

#     def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
#         logger.warning("LoadBalancerNode: not yet implemented")
#         return None

#     def live_outputs(self, pulumi_outputs, project, region) -> dict:
#         return {"ip_address": pulumi_outputs.get("ip", "")}

#     def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
#         name = pulumi_outputs.get("name", "")
#         if not name:
#             return None
#         return LogSource(
#             filter=(
#                 f'resource.type="http_load_balancer"'
#                 f' AND resource.labels.forwarding_rule_name="{name}"'
#             ),
#             project=project,
#         )