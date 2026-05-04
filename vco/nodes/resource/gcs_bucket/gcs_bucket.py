"""
nodes/resource/gcs_bucket/gcs_bucket.py — Cloud Storage Bucket resource node (fully self-describing).

Changes from previous version
------------------------------
  • Added iam_binding input port (so IamBindingNode can wire into this bucket).
  • BUCKET output port type changed to STORAGE (unified port scheme).
  • Added ALL missing Pulumi GCS Bucket parameters:
      - cors                    : Cross-Origin Resource Sharing rules
      - logging                 : Access & Storage Logs target bucket
      - retention_days          : Data retention policy (object lock)
      - soft_delete_days        : Soft-delete retention window
      - autoclass               : Automatic storage-class management
      - rpo                     : Recovery Point Objective (turbo replication)
      - custom_placement        : Dual-region custom placement
      - hierarchical_namespace  : Folder-like namespace (HNS / data lake)
      - enable_object_retention : Per-object retention locks
      - default_event_based_hold: Auto event-based hold on new objects
      - requester_pays          : Requester-pays billing mode
      - public_access_prevention: Org-policy-style public access prevention
      - ip_filter               : IP-range allow/deny filter
      - encryption_key          : Customer-managed encryption key (CMEK)
      - labels                  : Arbitrary key/value labels

Topology
--------
  GcsBucketNode ──(STORAGE)──► CloudRunNode         (env: GCS_BUCKET_<NAME>)
  GcsBucketNode ──(STORAGE)──► EventarcTriggerNode

  CloudRunNode  ──(STORAGE)──► GcsBucketNode  ← writers wired IN
  WorkflowNode  ──(STORAGE)──► GcsBucketNode  ← writers wired IN

  IamBindingNode ──(IAM_BINDING)──► GcsBucketNode

Writers wired INTO the bucket input port get:
  • GCS_BUCKET_<BUCKET_NAME> env var injected into them (for CR)
  • bucket name exported to deployed_outputs (for Workflows YAML)

The bucket also grants the wired writer's SA (if any) roles/storage.objectCreator
so the Cloud Run / Workflow SA can write without extra IAM steps.

Equivalent gcloud
-----------------
  gcloud storage buckets create --location=${LOCATION} gs://${BUCKET_NAME}
  gcloud storage buckets update gs://${BUCKET_NAME} --uniform-bucket-level-access
  gcloud storage buckets add-iam-policy-binding gs://${BUCKET_NAME} \\
    --member=allUsers --role=roles/storage.objectViewer
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class GcsBucketNode(GCPNode):
    """
    Cloud Storage Bucket.

    Inputs  (writers)  : any compute node that writes objects → bucket grants it objectCreator
    Outputs (consumers): STORAGE → CloudRun (env var), EventarcTriggerNode (trigger source)

    IAM: wire IamBindingNode → this bucket for fine-grained IAM grants.
        e.g. grant allUsers roles/storage.objectViewer for public read.

    Supports all GCS Pulumi parameters including CORS, lifecycle, versioning,
    logging, retention, soft-delete, autoclass, RPO, CMEK, IP filter, labels, and more.
    """

    inputs: ClassVar = [
        Port("writers",         PortType.STORAGE,         required=False, multi=True, multi_in=True),
        Port("service_account", PortType.SERVICE_ACCOUNT, required=False),
        Port("iam_binding",     PortType.IAM_BINDING,     required=False, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("storage", PortType.STORAGE, multi=True),   # → CloudRun (env var reader)
        Port("events",  PortType.STORAGE, multi=True),   # → EventarcTriggerNode (trigger source)
    ]

    node_color:  ClassVar = "#fbbf24"
    icon:        ClassVar = "gcsBucket"
    category:    ClassVar = "Storage"
    description: ClassVar = (
        "Cloud Storage Bucket — אחסון אובייקטים מנוהל ב-GCS. "
        "תומך ב-lifecycle, versioning, CORS, CMEK, retention, autoclass, HNS ועוד."
    )

    # ------------------------------------------------------------------
    # Edge wiring
    # ------------------------------------------------------------------

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        # ── Output edges: this bucket → consumers ──────────────────────────
        if src_id == self.node_id:
            if tgt_type == "CloudRunNode":
                ctx[tgt_id].setdefault("bucket_ids", []).append(self.node_id)
                return True
            if tgt_type == "EventarcTriggerNode":
                ctx[tgt_id]["bucket_source_id"] = self.node_id
                return True

        # ── Input edges: writers → this bucket ────────────────────────────
        if tgt_id == self.node_id:
            if src_type in ("CloudRunNode", "WorkflowNode"):
                ctx[self.node_id].setdefault("writer_ids", []).append(src_id)
                ctx[src_id].setdefault("bucket_ids", []).append(self.node_id)
                return True

        return False

    def dag_deps(self, ctx) -> list[str]:
        return list(ctx.get("writer_ids", []))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_labels(raw: str) -> dict[str, str]:
        """Parse 'key1=value1,key2=value2' into a dict."""
        result = {}
        for pair in raw.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, _, v = pair.partition("=")
                result[k.strip()] = v.strip()
        return result

    @staticmethod
    def _parse_list(raw: str) -> list[str]:
        """Parse comma-separated string into a list of non-empty strings."""
        return [x.strip() for x in raw.split(",") if x.strip()]

    # ------------------------------------------------------------------
    # Pulumi program
    # ------------------------------------------------------------------

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        writer_ids = ctx.get("writer_ids", [])

        def program() -> None:
            try:
                bucket_name   = props.get("name") or _resource_name(node_dict)
                location      = props.get("location", "EU")
                storage_class = props.get("storage_class", "STANDARD")
                uniform       = props.get("uniform_access", True)
                public_access = props.get("public_access", False)
                pub_prev      = props.get("public_access_prevention", "inherited")

                # ── Versioning ────────────────────────────────────────────────
                versioning    = props.get("versioning", False)

                # ── Lifecycle rules ───────────────────────────────────────────
                lifecycle_rules = []
                lifecycle_age = int(props.get("lifecycle_age", 0))
                if lifecycle_age > 0:
                    lifecycle_rules.append(
                        gcp.storage.BucketLifecycleRuleArgs(
                            action=gcp.storage.BucketLifecycleRuleActionArgs(type="Delete"),
                            condition=gcp.storage.BucketLifecycleRuleConditionArgs(age=lifecycle_age),
                        )
                    )

                noncurrent_age = int(props.get("lifecycle_noncurrent_age", 0))
                if noncurrent_age > 0:
                    # Delete old (noncurrent) versions after N days
                    lifecycle_rules.append(
                        gcp.storage.BucketLifecycleRuleArgs(
                            action=gcp.storage.BucketLifecycleRuleActionArgs(type="Delete"),
                            condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                                num_newer_versions=1,
                                days_since_noncurrent_time=noncurrent_age,
                                send_age_if_zero=False,
                            ),
                        )
                    )

                abort_mpu_age = int(props.get("lifecycle_abort_mpu_age", 0))
                if abort_mpu_age > 0:
                    # Abort stale incomplete multipart uploads
                    lifecycle_rules.append(
                        gcp.storage.BucketLifecycleRuleArgs(
                            action=gcp.storage.BucketLifecycleRuleActionArgs(
                                type="AbortIncompleteMultipartUpload"
                            ),
                            condition=gcp.storage.BucketLifecycleRuleConditionArgs(
                                age=abort_mpu_age
                            ),
                        )
                    )

                # ── Soft Delete Policy ────────────────────────────────────────
                soft_delete_days = int(props.get("soft_delete_days", 0))
                soft_delete_policy = None
                if soft_delete_days > 0:
                    soft_delete_policy = gcp.storage.BucketSoftDeletePolicyArgs(
                        retention_duration_seconds=soft_delete_days * 86400,
                    )

                # ── Retention Policy ──────────────────────────────────────────
                retention_days   = int(props.get("retention_days", 0))
                retention_locked = props.get("retention_locked", False)
                retention_policy = None
                if retention_days > 0:
                    retention_policy = gcp.storage.BucketRetentionPolicyArgs(
                        retention_period=str(retention_days * 86400),
                        is_locked=retention_locked,
                    )

                # ── Autoclass ─────────────────────────────────────────────────
                autoclass = props.get("autoclass", False)
                autoclass_terminal = props.get("autoclass_terminal_class", "")
                autoclass_cfg = None
                if autoclass:
                    autoclass_cfg = gcp.storage.BucketAutoclassArgs(
                        enabled=True,
                        **({"terminal_storage_class": autoclass_terminal} if autoclass_terminal else {}),
                    )

                # ── RPO ───────────────────────────────────────────────────────
                rpo = props.get("rpo", "") or None

                # ── CORS ──────────────────────────────────────────────────────
                cors_origins = self._parse_list(props.get("cors_origins", ""))
                cors_cfg = None
                if cors_origins:
                    cors_methods  = self._parse_list(props.get("cors_methods", "GET,HEAD"))
                    cors_max_age  = int(props.get("cors_max_age_seconds", 3600))
                    cors_cfg = [
                        gcp.storage.BucketCorArgs(
                            origins=cors_origins,
                            methods=cors_methods,
                            response_headers=["*"],
                            max_age_seconds=cors_max_age,
                        )
                    ]

                # ── Logging ───────────────────────────────────────────────────
                log_bucket = props.get("log_bucket", "").strip()
                log_prefix = props.get("log_prefix", "").strip()
                logging_cfg = None
                if log_bucket:
                    logging_cfg = gcp.storage.BucketLoggingArgs(
                        log_bucket=log_bucket,
                        **({"log_object_prefix": log_prefix} if log_prefix else {}),
                    )

                # ── Custom Placement (dual-region) ────────────────────────────
                placement_raw = props.get("custom_placement_regions", "").strip()
                custom_placement = None
                if placement_raw:
                    regions = self._parse_list(placement_raw)
                    if len(regions) == 2:
                        custom_placement = gcp.storage.BucketCustomPlacementConfigArgs(
                            data_locations=regions,
                        )
                    else:
                        logger.warning(
                            "custom_placement_regions must have exactly 2 regions; ignoring. Got: %s",
                            regions,
                        )

                # ── Hierarchical Namespace ────────────────────────────────────
                hns = props.get("hierarchical_namespace", False)
                hns_cfg = gcp.storage.BucketHierarchicalNamespaceArgs(enabled=True) if hns else None

                # ── IP Filter ─────────────────────────────────────────────────
                ip_mode  = props.get("ip_filter_mode", "").strip()
                ip_cidrs = self._parse_list(props.get("ip_filter_cidrs", ""))
                ip_filter_cfg = None
                if ip_mode in ("Enabled", "Disabled"):
                    ip_filter_cfg = gcp.storage.BucketIpFilterArgs(
                        mode=ip_mode,

                        # חובה כש־Enabled, אחרת לא לשים בכלל
                        allow_all_service_agent_access=(
                            True if ip_mode == "Enabled" else None
                        ),

                        # רק אם יש CIDRs
                        public_network_source=(
                            gcp.storage.BucketIpFilterPublicNetworkSourceArgs(
                                allowed_ip_cidr_ranges=ip_cidrs or ["0.0.0.0/0", "::/0"],
                            )
                            if ip_cidrs else None
                        ),
                    )

                # ── Encryption (CMEK) ─────────────────────────────────────────
                cmek = props.get("encryption_key", "").strip()
                encryption_cfg = None
                if cmek:
                    encryption_cfg = gcp.storage.BucketEncryptionArgs(
                        default_kms_key_name=cmek,
                    )

                # ── Labels ────────────────────────────────────────────────────
                labels_raw = props.get("labels", "").strip()
                labels = self._parse_labels(labels_raw) if labels_raw else None

                # ── Website ───────────────────────────────────────────────────
                website_main = props.get("website_main_page", "").strip()
                website_404  = props.get("website_not_found_page", "").strip()
                website_cfg  = None
                if website_main:
                    website_cfg = gcp.storage.BucketWebsiteArgs(
                        main_page_suffix=website_main,
                        **({"not_found_page": website_404} if website_404 else {}),
                    )

                # ── Object-level options ──────────────────────────────────────
                enable_obj_retention = props.get("enable_object_retention", False)
                default_hold         = props.get("default_event_based_hold", False)
                requester_pays       = props.get("requester_pays", False)

                # ── Create bucket ─────────────────────────────────────────────
                b = gcp.storage.Bucket(
                    self.node_id,
                    name=bucket_name,
                    location=location,
                    storage_class=storage_class,
                    project=project,
                    uniform_bucket_level_access=uniform,
                    public_access_prevention=pub_prev,
                    versioning=(
                        gcp.storage.BucketVersioningArgs(enabled=True) if versioning else None
                    ),
                    lifecycle_rules=lifecycle_rules or None,
                    soft_delete_policy=soft_delete_policy,
                    retention_policy=retention_policy,
                    autoclass=autoclass_cfg,
                    rpo=rpo,
                    cors=cors_cfg,
                    logging=logging_cfg,
                    custom_placement_config=custom_placement,
                    hierarchical_namespace=hns_cfg,
                    ip_filter=ip_filter_cfg,
                    encryption=encryption_cfg,
                    labels=labels,
                    website=website_cfg,
                    enable_object_retention=enable_obj_retention or None,
                    default_event_based_hold=default_hold or None,
                    requester_pays=requester_pays or None,
                    force_destroy=True,
                )

                # ── Public read IAM ───────────────────────────────────────────
                # Equivalent:
                #   gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \
                #     --member=allUsers --role=roles/storage.objectViewer
                if public_access:
                    gcp.storage.BucketIAMBinding(
                        f"{self.node_id}-public-read",
                        bucket=b.name,
                        role="roles/storage.objectViewer",
                        members=["allUsers"],
                    )

                # ── Grant objectCreator to every wired writer SA ──────────────
                sa_emails: list[str] = []
                for wid in writer_ids:
                    email = deployed_outputs.get(wid, {}).get("sa_email", "")
                    if not email:
                        email = deployed_outputs.get(wid, {}).get("email", "")
                    if email and email not in sa_emails:
                        sa_emails.append(email)

                if sa_emails:
                    gcp.storage.BucketIAMBinding(
                        f"{self.node_id}-writer-binding",
                        bucket=b.name,
                        role="roles/storage.objectCreator",
                        members=[f"serviceAccount:{e}" for e in sa_emails],
                    )

                pulumi.export("name", b.name)
                pulumi.export("url",  b.url)
                pulumi.export("id",   b.id)
            except Exception as e:
                logger.error("program() crashed: %s", e, exc_info=True)
                raise

        return program

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        return {
            "name": pulumi_outputs.get("name", ""),
            "url":  pulumi_outputs.get("url",  ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="gcs_bucket"'
                f' AND resource.labels.bucket_name="{name}"'
            ),
            project=project,
        )
        