"""
nodes/gcs_bucket.py — Cloud Storage Bucket resource node (fully self-describing).

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

    params_schema: ClassVar = [
        # ── Basic ──────────────────────────────────────────────────────────
        {
            "key": "name", "label": "Bucket Name",
            "type": "text", "default": "", "placeholder": "my-project-bucket",
            "description": "שם הבאקט ב-GCS. חייב להיות ייחודי גלובלית, lowercase ועד 63 תווים.",
        },
        {
            "key": "location", "label": "Location",
            "type": "select",
            "options": [
                "EU", "US", "ASIA",
                "me-west1", "us-central1", "us-east1", "us-west1",
                "europe-west1", "europe-west2", "europe-west3",
                "asia-east1", "asia-northeast1", "asia-southeast1",
                "northamerica-northeast1", "southamerica-east1",
                "australia-southeast1",
            ],
            "default": "EU",
            "category" : "Basic",
            "description": (
                "המיקום הגיאוגרפי של הבאקט. לא ניתן לשנות לאחר יצירה. "
                "EU/US/ASIA = multi-region (זמינות גבוהה). "
                "us-central1 וכו' = single-region (עלות נמוכה יותר)."
            ),
        },
        {
            "key": "storage_class", "label": "Storage Class",
            "type": "select",
            "options": ["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"],
            "default": "STANDARD",
            "category": "Basic",
            "description": (
                "סוג האחסון: "
                "STANDARD — גישה תכופה, ביצועים גבוהים. "
                "NEARLINE — גישה פחות מפעם בחודש (זול יותר). "
                "COLDLINE — גישה פחות מפעם ברבעון. "
                "ARCHIVE — ארכיב לטווח ארוך, גישה נדירה מאוד."
            ),
        },

        # ── Access & Security ──────────────────────────────────────────────
        {
            "key": "uniform_access", "label": "Uniform Bucket-Level Access",
            "type": "checkbox", "default": True,
            "description": (
                "מאפשר שליטה מרכזית על הרשאות באמצעות IAM בלבד (ללא ACLs ישנים). "
                "מומלץ תמיד. "
                "gcloud: --uniform-bucket-level-access"
            ),
            "category": "Access & Security",
        },
        {
            "key": "public_access", "label": "Allow Public Read (allUsers objectViewer)",
            "type": "checkbox", "default": False,
            "description": (
                "מוסיף IAM binding שמאפשר לכל אחד (allUsers) לקרוא אובייקטים. "
                "שימושי לאתרים סטטיים או נכסים ציבוריים. "
                "gcloud: --member=allUsers --role=roles/storage.objectViewer"
            ),
            "category": "Access & Security",
        },
        {
            "key": "public_access_prevention", "label": "Public Access Prevention",
            "type": "select",
            "options": ["inherited", "enforced"],
            "default": "inherited",
            "description": (
                "inherited — הגדרות ציבוריות נורשות מ-Org Policy. "
                "enforced — חוסם כל גישה ציבורית (גם אם public_access=True). "
                "שימושי לסביבות פרודאקשן רגישות."
            ),
        },

        # ── Versioning & Lifecycle ─────────────────────────────────────────
        {
            "key": "versioning", "label": "Object Versioning",
            "type": "checkbox", "default": False,
            "description": (
                "שומר גרסאות ישנות של קבצים בעת דריסה/מחיקה. "
                "מגן מפני מחיקה בשוגג. מגדיל עלויות אחסון."
            ),
        },
        {
            "key": "lifecycle_age", "label": "Auto-Delete After N Days (0=off)",
            "type": "number", "default": 0,
            "description": (
                "מחיקה אוטומטית של אובייקטים שגילם עולה על N ימים. "
                "0 = מבוטל. שימושי לבאקטים זמניים, לוגים, backups."
            ),
        },
        {
            "key": "lifecycle_noncurrent_age", "label": "Auto-Delete Noncurrent Versions After N Days (0=off)",
            "type": "number", "default": 0,
            "description": (
                "כאשר Versioning פעיל: מוחק גרסאות ישנות (noncurrent) לאחר N ימים. "
                "0 = מבוטל. מאפשר versioning בלי שהעלות תגדל ללא גבול."
            ),
        },
        {
            "key": "lifecycle_abort_mpu_age", "label": "Abort Incomplete Multipart Uploads After N Days (0=off)",
            "type": "number", "default": 0,
            "description": (
                "מבטל uploads חלקיים (multipart) שלא הושלמו תוך N ימים. "
                "מונע חיוב על uploads 'תקועים'. מומלץ להגדיר ל-1 כברירת מחדל."
            ),
        },

        # ── Soft Delete ────────────────────────────────────────────────────
        {
            "key": "soft_delete_days", "label": "Soft Delete Retention (Days, 0=default)",
            "type": "number", "default": 0,
            "description": (
                "מספר ימים שבהם אובייקטים שנמחקו עדיין ניתנים לשחזור (soft-delete). "
                "0 = ברירת מחדל של GCS (7 ימים). "
                "הגדר ל-0 עם retention_seconds=0 כדי לבטל לחלוטין."
            ),
        },

        # ── Retention Policy ───────────────────────────────────────────────
        {
            "key": "retention_days", "label": "Retention Policy (Days, 0=off)",
            "type": "number", "default": 0,
            "description": (
                "נועל אובייקטים מפני מחיקה/שינוי לפחות N ימים (Object Lock). "
                "0 = מבוטל. שימושי לציות רגולטורי (WORM compliance)."
            ),
        },
        {
            "key": "retention_locked", "label": "Lock Retention Policy (irreversible!)",
            "type": "checkbox", "default": False,
            "description": (
                "נועל את ה-Retention Policy עצמו — לא ניתן להסיר/לקצר לאחר מכן. "
                "אזהרה: פעולה בלתי הפיכה! מיועד לדרישות ציות קפדניות."
            ),
        },

        # ── Autoclass ──────────────────────────────────────────────────────
        {
            "key": "autoclass", "label": "Autoclass (Auto Storage-Class Management)",
            "type": "checkbox", "default": False,
            "description": (
                "GCS מנהל אוטומטית את ה-Storage Class של כל אובייקט לפי דפוסי גישה. "
                "מוריד עלויות בלי לשנות קוד. לא ניתן לשלב עם Nearline/Coldline/Archive ידניים."
            ),
        },
        {
            "key": "autoclass_terminal_class", "label": "Autoclass Terminal Storage Class",
            "type": "select",
            "options": ["", "NEARLINE", "ARCHIVE"],
            "default": "",
            "description": (
                "מחלקת האחסון הסופית שאוטומטית לא תרד ממנה (רלוונטי רק כשאוטומטי פעיל). "
                "NEARLINE = חיסכון בינוני. ARCHIVE = חיסכון מקסימלי לנתונים קרים מאוד."
            ),
        },

        # ── RPO / Replication ──────────────────────────────────────────────
        {
            "key": "rpo", "label": "RPO (Recovery Point Objective)",
            "type": "select",
            "options": ["", "DEFAULT", "ASYNC_TURBO"],
            "default": "",
            "description": (
                "רלוונטי רק ל-dual-region ו-multi-region buckets. "
                "DEFAULT = רפליקציה סטנדרטית (async). "
                "ASYNC_TURBO = Turbo Replication, RPO של 15 דקות (dual-region בלבד, תוספת עלות)."
            ),
        },

        # ── CORS ──────────────────────────────────────────────────────────
        {
            "key": "cors_origins", "label": "CORS Origins (comma-separated, empty=disabled)",
            "type": "text", "default": "",
            "placeholder": "https://myapp.com,https://admin.myapp.com",
            "description": (
                "מאפשר גישה מ-browser מ-origin אחר (CORS). "
                "הכנס origins מופרדים בפסיק. "
                "ריק = ללא CORS. "
                "שימושי כשמשרתים קבצים ישירות ל-browser (SPA, תמונות, JS)."
            ),
        },
        {
            "key": "cors_methods", "label": "CORS Methods",
            "type": "text", "default": "GET,HEAD",
            "description": (
                "HTTP methods מותרים ב-CORS. "
                "לקריאה בלבד: GET,HEAD. "
                "לכתיבה מה-browser: GET,HEAD,PUT,POST,DELETE."
            ),
        },
        {
            "key": "cors_max_age_seconds", "label": "CORS Max Age (seconds)",
            "type": "number", "default": 3600,
            "description": (
                "כמה זמן הדפדפן יכול לשמור preflight CORS response ב-cache. "
                "3600 = שעה. ערך גבוה = פחות בקשות OPTIONS, ביצועים טובים יותר."
            ),
        },

        # ── Logging ───────────────────────────────────────────────────────
        {
            "key": "log_bucket", "label": "Access Log Target Bucket (empty=disabled)",
            "type": "text", "default": "",
            "placeholder": "my-logs-bucket",
            "description": (
                "שם הבאקט שאליו יישמרו לוגי גישה (Access & Storage Logs). "
                "ריק = לוגים מבוטלים. "
                "הבאקט היעד חייב להיות באותו פרויקט."
            ),
        },
        {
            "key": "log_prefix", "label": "Access Log Object Prefix",
            "type": "text", "default": "",
            "placeholder": "logs/my-bucket/",
            "description": (
                "prefix שיתווסף לשם הקבצים של לוגי הגישה בבאקט היעד. "
                "שימושי להפרדה בין לוגים של באקטים שונים באותו log bucket."
            ),
        },

        # ── Custom Placement (Dual-region) ────────────────────────────────
        {
            "key": "custom_placement_regions", "label": "Custom Dual-Region Placement (comma-separated, empty=off)",
            "type": "text", "default": "",
            "placeholder": "us-central1,us-east1",
            "description": (
                "בחר בדיוק שתי regions ל-dual-region bucket מותאם אישית. "
                "ריק = ברירת מחדל של ה-location. "
                "דורש שה-location תהיה multi-region (US/EU/ASIA)."
            ),
        },

        # ── Hierarchical Namespace ────────────────────────────────────────
        {
            "key": "hierarchical_namespace", "label": "Hierarchical Namespace (HNS / Data Lake)",
            "type": "checkbox", "default": False,
            "description": (
                "מאפשר ניהול תיקיות אמיתיות בבאקט (כמו Azure Data Lake / HDFS). "
                "חובה: uniform_access=True. "
                "שימושי ל-BigQuery, Dataproc, pipelines של data lake."
            ),
        },

        # ── Object Retention & Holds ──────────────────────────────────────
        {
            "key": "enable_object_retention", "label": "Enable Per-Object Retention Locks",
            "type": "checkbox", "default": False,
            "description": (
                "מאפשר נעילת retention ברמת אובייקט בודד (object-level retention lock). "
                "שונה מ-Retention Policy שחל על כל הבאקט. "
                "מיועד ל-compliance ו-legal hold."
            ),
        },
        {
            "key": "default_event_based_hold", "label": "Default Event-Based Hold on New Objects",
            "type": "checkbox", "default": False,
            "description": (
                "כל אובייקט חדש יוצר אוטומטית עם event-based hold פעיל. "
                "הוld חוסם מחיקה/שינוי עד שמשחררים אותו ידנית (release hold). "
                "שימושי לתהליכי legal hold אוטומטיים."
            ),
        },

        # ── Billing ───────────────────────────────────────────────────────
        {
            "key": "requester_pays", "label": "Requester Pays",
            "type": "checkbox", "default": False,
            "description": (
                "המשתמש שמוריד/מעלה נתונים משלם על עלויות הרשת והפעולות (לא בעל הבאקט). "
                "שימושי לפצרות public data שרוצות לחלוק נתונים בלי לשלם על bandwidth."
            ),
        },

        # ── IP Filter ─────────────────────────────────────────────────────
        {
            "key": "ip_filter_mode", "label": "IP Filter Mode",
            "type": "select",
            "options": ["", "Enabled", "Disabled"],
            "default": "",
            "description": (
                "מגביל גישה לבאקט לפי כתובות IP. "
                "Enabled = רק ה-CIDRs שהוגדרו מורשים. "
                "Disabled = הפילטר קיים אך מבוטל. "
                "ריק = ללא IP filter."
            ),
        },
        {
            "key": "ip_filter_cidrs", "label": "IP Filter Allowed CIDRs (comma-separated)",
            "type": "text", "default": "",
            "placeholder": "10.0.0.0/8,192.168.1.0/24",
            "description": (
                "רשימת CIDR ranges מורשות לגישה לבאקט כשה-IP filter פעיל. "
                "לגישה ציבורית מלאה: 0.0.0.0/0,::/0"
            ),
        },

        # ── Encryption ────────────────────────────────────────────────────
        {
            "key": "encryption_key", "label": "CMEK Key (Customer-Managed Encryption Key, empty=Google-managed)",
            "type": "text", "default": "",
            "placeholder": "projects/my-project/locations/global/keyRings/my-ring/cryptoKeys/my-key",
            "description": (
                "מפתח הצפנה מנוהל-לקוח מ-Cloud KMS (CMEK). "
                "ריק = הצפנה ב-Google-managed key (ברירת מחדל, מאובטח). "
                "CMEK נדרש לציות מסוים (HIPAA, FedRAMP) שדורש שליטה מלאה על המפתחות."
            ),
        },

        # ── Labels ────────────────────────────────────────────────────────
        {
            "key": "labels", "label": "Labels (key=value, comma-separated)",
            "type": "text", "default": "",
            "placeholder": "env=prod,team=backend,cost-center=42",
            "description": (
                "תגיות key=value שמאפשרות ניהול, חיפוש ומעקב עלויות. "
                "פורמט: key1=value1,key2=value2. "
                "מופיעות בחיובי GCP ומאפשרות פילטור במסוף."
            ),
        },

        # ── Website ───────────────────────────────────────────────────────
        {
            "key": "website_main_page", "label": "Static Website Main Page (empty=off)",
            "type": "text", "default": "",
            "placeholder": "index.html",
            "description": (
                "מגדיר את הבאקט כ-static website host. "
                "קובץ ה-index שמוגש לבקשות לתיקיות. "
                "ריק = הבאקט לא מוגדר כאתר. דורש public_access=True לגישה ציבורית."
            ),
        },
        {
            "key": "website_not_found_page", "label": "Static Website 404 Page",
            "type": "text", "default": "",
            "placeholder": "404.html",
            "description": (
                "קובץ שמוגש כשנדרש אובייקט שלא קיים (HTTP 404). "
                "רלוונטי רק כש-website_main_page מוגדר."
            ),
        },
    ]

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