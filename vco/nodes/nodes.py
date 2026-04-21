from dataclasses import dataclass, field
from typing import ClassVar
from nodes.base_node import GCPNode, Port
from nodes.port_types import PortType


# ── Compute ───────────────────────────────────────────────────────────────────

@dataclass
class CloudRunNode(GCPNode):
    service_name:  str  = ""
    image:         str  = ""
    memory:        str  = "512Mi"
    region:        str  = "me-west1"
    cpu:           str  = "1"
    min_instances: int  = 0
    max_instances: int  = 10
    port:          int  = 8080
    env_vars:      dict = field(default_factory=dict)
    service_url:   str  = ""

    params_schema: ClassVar = [
        {"key": "service_name",  "label": "Service Name",     "type": "text",   "default": "", "placeholder": "your-service-name"},
        {"key": "image",         "label": "Container Image", "type": "text",   "default": "", "placeholder": "gcr.io/project/image:tag"},
        {"key": "memory",        "label": "Memory",          "type": "select", "options": ["256Mi","512Mi","1Gi","2Gi","4Gi","8Gi"], "default": "512Mi"},
        {"key": "cpu",           "label": "CPU",             "type": "select", "options": ["1","2","4","8"], "default": "1"},
        {"key": "min_instances", "label": "Min Instances",   "type": "number", "default": 0},
        {"key": "max_instances", "label": "Max Instances",   "type": "number", "default": 10},
        {"key": "port",          "label": "Port",            "type": "number", "default": 8080},
        {"key": "region",        "label": "Region",          "type": "select", "options": ["me-west1","us-central1","us-east1"], "default": "me-west1"},
        {"key": "service_url",   "label": "Service URL",     "type": "text",   "default": "", "placeholder": "https://my-service.run.app"},
    ]
    url_field: ClassVar = "service_url"   # ← השדה שמכיל את ה־URL

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        # Port("network",         PortType.NETWORK),
        # multi_in=True: multiple secrets can be mounted on the same CR
        Port("secret",          PortType.SECRET, multi=True, multi_in=True),
        Port("MESSAGE",         PortType.MESSAGE, multi=True, multi_in=True), # אפשר גם לקבל הודעות ישירות מ־Pub/Sub
    ]
    outputs: ClassVar = [
        Port("publishes_to",    PortType.TOPIC,   multi=True),
        Port("writes_to",       PortType.STORAGE, multi=True),
    ]
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloudRun"
    category:    ClassVar = "Compute"
    description: ClassVar = "Serverless container runtime"


@dataclass
class CloudFunctionNode(GCPNode):
    runtime:     str = "python311"
    entry_point: str = "main"
    memory:      str = "256Mi"
    timeout:     int = 60
    trigger:     str = "http"   # http | pubsub | storage

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("trigger_topic",   PortType.TOPIC),
        Port("secret",          PortType.SECRET, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to",    PortType.TOPIC,   multi=True),
        Port("writes_to",       PortType.STORAGE, multi=True),
    ]
    node_color:  ClassVar = "#a78bfa"
    icon:        ClassVar = "cloudFunctions"
    category:    ClassVar = "Compute"
    description: ClassVar = "Event-driven serverless function"


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class CloudSQLNode(GCPNode):
    tier:             str  = "db-f1-micro"
    database_version: str  = "POSTGRES_15"
    region:           str  = "us-central1"
    disk_size_gb:     int  = 10
    ha:               bool = False

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("network",         PortType.NETWORK, required=True),
    ]
    outputs: ClassVar = [
        # multi=True: many services can connect to the same DB output handle
        Port("connection",      PortType.DATABASE, multi=True),
    ]
    node_color:  ClassVar = "#f97316"
    icon:        ClassVar = "cloudSql"
    category:    ClassVar = "Data"
    description: ClassVar = "Managed relational database"


@dataclass
class BigQueryNode(GCPNode):
    location:      str = "US"
    dataset_id:    str = ""
    partition_by:  str = ""
    expiration_ms: int = 0

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("writes_in",       PortType.STORAGE, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("query_out",       PortType.DATABASE, multi=True),
    ]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "bigquery"
    category:    ClassVar = "Data"
    description: ClassVar = "Serverless data warehouse"


@dataclass
class FirestoreNode(GCPNode):
    mode:      str = "NATIVE"   # NATIVE | DATASTORE_COMPAT
    location:  str = "us-central"
    ttl_field: str = ""

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
    ]
    outputs: ClassVar = [
        Port("document_ref",    PortType.DATABASE, multi=True),
    ]
    node_color:  ClassVar = "#f59e0b"
    icon:        ClassVar = "firestore"
    category:    ClassVar = "Data"
    description: ClassVar = "Serverless NoSQL document DB"


@dataclass
class MemorystoreNode(GCPNode):
    tier:           str = "BASIC"      # BASIC | STANDARD_HA
    memory_size_gb: int = 1
    redis_version:  str = "REDIS_7_0"
    region:         str = "us-central1"

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("network",         PortType.NETWORK, required=True),
    ]
    outputs: ClassVar = [
        Port("cache_endpoint",  PortType.DATABASE, multi=True),
    ]
    node_color:  ClassVar = "#ef4444"
    icon:        ClassVar = "memorystore"
    category:    ClassVar = "Data"
    description: ClassVar = "Managed Redis / Memcached"




# ── Storage ───────────────────────────────────────────────────────────────────

@dataclass
class GCSBucketNode(GCPNode):
    location:       str  = "US"
    storage_class:  str  = "STANDARD"
    versioning:     bool = False
    public_access:  bool = False
    lifecycle_days: int  = 0   # 0 = no lifecycle rule

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("bucket",          PortType.STORAGE, multi=True),
    ]
    # outputs: ClassVar = [
    #     Port("bucket",          PortType.STORAGE, multi=True),
    # ]
    node_color:  ClassVar = "#eab308"
    icon:        ClassVar = "cloudStorage"
    category:    ClassVar = "Storage"
    description: ClassVar = "Object storage bucket"


# ── Security ──────────────────────────────────────────────────────────────────

@dataclass
class ServiceAccountNode(GCPNode):
    roles:          list = field(default_factory=list)
    description_sa: str  = ""

    inputs: ClassVar = []
    outputs: ClassVar = [
        Port("identity",        PortType.SERVICE_ACCOUNT, multi=True),
    ]
    node_color:  ClassVar = "#8b5cf6"
    icon:        ClassVar = "security"
    category:    ClassVar = "Security"
    description: ClassVar = "IAM service identity"


@dataclass
class SecretManagerNode(GCPNode):
    replication:   str = "automatic"
    rotation_days: int = 0

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
    ]
    outputs: ClassVar = [
        Port("secret_ref",      PortType.SECRET, multi=True),
    ]
    node_color:  ClassVar = "#ec4899"
    icon:        ClassVar = "secretManager"
    category:    ClassVar = "Security"
    description: ClassVar = "Encrypted secrets store"


# ── Networking ────────────────────────────────────────────────────────────────

@dataclass
class VirtualPrivateCloudNode(GCPNode):
    subnet_cidr:           str  = "10.0.0.0/24"
    region:                str  = "us-central1"
    private_google_access: bool = True

    inputs: ClassVar = []
    outputs: ClassVar = [
        Port("subnet",          PortType.NETWORK, multi=True),
    ]
    node_color:  ClassVar = "#2c10b9"
    icon:        ClassVar = "VirtualPrivateCloud"
    category:    ClassVar = "Networking"
    description: ClassVar = "Virtual private network"


# @dataclass
# class GroupBoxNode(GCPNode):
#     title: str = "Visual Group"

#     inputs: ClassVar = []
#     outputs: ClassVar = []
#     node_color:  ClassVar = "#8b5cf6"
#     icon:        ClassVar = "layers"
#     category:    ClassVar = "Grouping"
#     description: ClassVar = "Visual container for grouping nodes on the canvas"


@dataclass
class LoadBalancerNode(GCPNode):
    lb_type:     str  = "EXTERNAL"   # EXTERNAL | INTERNAL
    protocol:    str  = "HTTPS"      # HTTP | HTTPS | TCP | UDP
    ssl_cert:    str  = ""
    cdn_enabled: bool = False

    inputs: ClassVar = [
        Port("network",         PortType.NETWORK, required=True),
        # multi_in=True: multiple backend services can register under one LB
        Port("backend",         PortType.NETWORK, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("frontend_ip",     PortType.NETWORK, multi=True),
    ]
    node_color:  ClassVar = "#06b6d4"
    icon:        ClassVar = "cloudLoadBalancing"
    category:    ClassVar = "LoadBalancer"
    description: ClassVar = "HTTP(S) / TCP / UDP load balancer"