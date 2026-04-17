from dataclasses import dataclass, field
from typing import ClassVar
from base_node import GCPNode, Port
from port_types import PortType


# ── Compute ───────────────────────────────────────────────────────────────────

@dataclass
class CloudRunNode(GCPNode):
    image:         str  = ""
    memory:        str  = "512Mi"
    cpu:           str  = "1"
    min_instances: int  = 0
    max_instances: int  = 10
    port:          int  = 8080
    env_vars:      dict = field(default_factory=dict)

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("network",         PortType.NETWORK),
        # multi_in=True: multiple secrets can be mounted on the same CR
        Port("secret",          PortType.SECRET, multi=True, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to",    PortType.TOPIC,   multi=True),
        Port("writes_to",       PortType.STORAGE, multi=True),
    ]
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloud"
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
    icon:        ClassVar = "zap"
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
    icon:        ClassVar = "database"
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
    icon:        ClassVar = "table"
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
    icon:        ClassVar = "layers"
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
    icon:        ClassVar = "zap"
    category:    ClassVar = "Data"
    description: ClassVar = "Managed Redis / Memcached"


# ── Messaging ─────────────────────────────────────────────────────────────────

@dataclass
class PubsubNode(GCPNode):
    ack_deadline_seconds:       int = 20
    message_retention_duration: str = "604800s"

    inputs: ClassVar = [
        # multi_in=True: many publishers (CR, CF…) can push to the same topic
        Port("topic_in",        PortType.TOPIC, multi_in=True),
    ]
    outputs: ClassVar = [
        Port("topic_out",       PortType.TOPIC, multi=True),
    ]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "radio"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Async messaging bus"


@dataclass
class SubscriptionNode(GCPNode):
    ack_deadline_seconds:  int  = 20
    retain_acked_messages: bool = False
    filter_expr:           str  = ""
    push_endpoint:         str  = ""   # empty = pull subscription

    inputs: ClassVar = [
        Port("topic",           PortType.TOPIC, required=True),
    ]
    outputs: ClassVar = [
        Port("delivers_to",     PortType.TOPIC, multi=True),
    ]
    node_color:  ClassVar = "#ec485b"
    icon:        ClassVar = "inbox"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Pub/Sub topic subscription"


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
    icon:        ClassVar = "archive"
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
    icon:        ClassVar = "user-check"
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
    icon:        ClassVar = "key"
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
    node_color:  ClassVar = "#10b981"
    icon:        ClassVar = "network"
    category:    ClassVar = "Networking"
    description: ClassVar = "Virtual private network"


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
    icon:        ClassVar = "globe"
    category:    ClassVar = "Networking"
    description: ClassVar = "HTTP(S) / TCP / UDP load balancer"