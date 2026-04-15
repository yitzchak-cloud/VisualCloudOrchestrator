from dataclasses import dataclass, field
from typing import ClassVar
from base_node import GCPNode, Port
from port_types import PortType


@dataclass
class CloudRunNode(GCPNode):
    image:        str = ""
    memory:       str = "512Mi"
    cpu:          str = "1"
    min_instances: int = 0
    max_instances: int = 10
    port:         int = 8080
    env_vars:     dict = field(default_factory=dict)

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("network",         PortType.NETWORK),
        Port("secret",          PortType.SECRET, multi=True),
    ]
    outputs: ClassVar = [
        Port("publishes_to",    PortType.TOPIC),
        Port("writes_to",       PortType.STORAGE),
    ]
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloud"
    description: ClassVar = "Serverless container runtime"


@dataclass
class CloudSQLNode(GCPNode):
    tier:         str = "db-f1-micro"
    database_version: str = "POSTGRES_15"
    region:       str = "us-central1"
    disk_size_gb: int = 10
    ha:           bool = False

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
        Port("network",         PortType.NETWORK, required=True),
    ]
    outputs: ClassVar = [
        Port("connection",      PortType.DATABASE),
    ]
    node_color:  ClassVar = "#f97316"
    icon:        ClassVar = "database"
    description: ClassVar = "Managed relational database"


@dataclass
class PubSubNode(GCPNode):
    ack_deadline_seconds: int = 20
    message_retention_duration: str = "604800s"

    inputs: ClassVar = [
        Port("topic_in",        PortType.TOPIC),
    ]
    outputs: ClassVar = [
        Port("topic_out",       PortType.TOPIC, multi=True),
    ]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "radio"
    description: ClassVar = "Async messaging bus"


@dataclass
class GCSBucketNode(GCPNode):
    location:          str = "US"
    storage_class:     str = "STANDARD"
    versioning:        bool = False
    public_access:     bool = False

    inputs: ClassVar = [
        Port("service_account", PortType.SERVICE_ACCOUNT, required=True),
    ]
    outputs: ClassVar = [
        Port("bucket",          PortType.STORAGE),
    ]
    node_color:  ClassVar = "#eab308"
    icon:        ClassVar = "archive"
    description: ClassVar = "Object storage bucket"


@dataclass
class ServiceAccountNode(GCPNode):
    roles: list = field(default_factory=list)
    description_sa: str = ""

    inputs: ClassVar = []
    outputs: ClassVar = [
        Port("identity",        PortType.SERVICE_ACCOUNT, multi=True),
    ]
    node_color:  ClassVar = "#8b5cf6"
    icon:        ClassVar = "user-check"
    description: ClassVar = "IAM service identity"


@dataclass
class VPCNode(GCPNode):
    subnet_cidr:   str = "10.0.0.0/24"
    region:        str = "us-central1"
    private_google_access: bool = True

    inputs: ClassVar = []
    outputs: ClassVar = [
        Port("subnet",          PortType.NETWORK, multi=True),
    ]
    node_color:  ClassVar = "#10b981"
    icon:        ClassVar = "network"
    description: ClassVar = "Virtual private network"


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
    description: ClassVar = "Encrypted secrets store"
