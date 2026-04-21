# from dataclasses import dataclass, field
# from typing import ClassVar
# from base_node import GCPNode, Port
# from port_types import PortType

# # ── Messaging ─────────────────────────────────────────────────────────────────

# # @dataclass
# # class PubsubNode(GCPNode):
# #     ack_deadline_seconds:       int = 20
# #     message_retention_duration: str = "604800s"
# #     # params_schema: ClassVar = [
# #     #     {
# #     #         "key": "port",
# #     #         "label": "Port",            
# #     #         "type": "number", 
# #     #         "default": 8080
# #     #     },
# #     # ]
# #     inputs: ClassVar = [
# #         # multi_in=True: many publishers (CR, CF…) can push to the same topic
# #         Port("topic_in",   PortType.TOPIC, multi_in=True),
# #         Port("Schema",     PortType.SCHEMA, multi_in=False),
# #     ]
# #     outputs: ClassVar = [
# #         Port("topic_out",       PortType.TOPIC, multi=True),
# #     ]
# #     node_color:  ClassVar = "#3b82f6"
# #     icon:        ClassVar = "radio"
# #     category:    ClassVar = "Messaging"
# #     description: ClassVar = "Async messaging bus"


# # @dataclass
# # class SubscriptionNode(GCPNode):
# #     ack_deadline_seconds:  int  = 20
# #     retain_acked_messages: bool = False
# #     filter_expr:           str  = ""
# #     push_endpoint:         str  = ""   # empty = pull subscription

# #     inputs: ClassVar = [
# #         Port("topic",           PortType.TOPIC, required=True),
# #     ]
# #     outputs: ClassVar = [
# #         Port("delivers_to",     PortType.TOPIC, multi=True),
# #     ]
# #     node_color:  ClassVar = "#ec485b"
# #     icon:        ClassVar = "inbox"
# #     category:    ClassVar = "Messaging"
# #     description: ClassVar = "Pub/Sub topic subscription"


# # # 

# # ── Messaging ─────────────────────────────────────────────────────────────────

# @dataclass
# class PubsubTopicNode(GCPNode):
#     message_retention_duration: str = "604800s"
#     kms_key_name:               str = ""

#     params_schema: ClassVar = [
#         {"key": "message_retention_duration", "label": "Retention Duration", "type": "text", "default": "604800s"},
#         {"key": "kms_key_name", "label": "KMS Key Name", "type": "text", "default": ""},
#     ]

#     inputs: ClassVar = [
#         # גורמים שמפרסמים לטופיק (Cloud Run, Functions וכו')
#         Port("publishers", PortType.TOPIC, multi_in=True),
#         Port("Schema",     PortType.SCHEMA, multi_in=False),
#     ]
#     outputs: ClassVar = [
#         # היציאה כעת היא מסוג SUBSCRIPTION כדי לחבר אליה צרכנים/סאבסקריפשנים
#         Port("subscriptions", PortType.SUBSCRIPTION, multi=True),
#     ]
#     node_color:  ClassVar = "#3b82f6"
#     icon:        ClassVar = "pubsub"
#     category:    ClassVar = "Messaging"
#     description: ClassVar = "Pub/Sub Topic - The core messaging hub"


# @dataclass
# class SchemaNode(GCPNode):
#     params_schema: ClassVar = [
#         {
#             "key": "name",
#             "label": "Schema Name",
#             "type": "text",
#             "placeholder": "Enter schema name",
#         },
#         {
#             "key": "type ",        
#             "label": "type of schema",          
#             "type": "select", 
#             "options": ["AVRO","PROTOCOL_BUFFER"], 
#             "default": "AVRO"},
#         {
#             "key": "protocol_buffer", 
#             "label": "Protocol Buffer Definition", 
#             "type": "textarea", 
#             "placeholder": "{\n  \"type\" : \"record\",\n  \"name\" : \"Avro\",\n  \"fields\" : [\n    {\n      \"name\" : \"StringField\",\n      \"type\" : \"string\"\n    },\n    {\n      \"name\" : \"IntField\",\n      \"type\" : \"int\"\n    }\n  ]\n}\n"
#         },
#         {
#             "key": "project",
#             "label": "Project ID",
#             "type": "text",
#             "default": ""
#         }
#     ]
#     outputs: ClassVar = [
#         Port("Schema", PortType.SCHEMA, multi=True),
#     ]
#     icon:        ClassVar = "pubsub"
#     category:    ClassVar = "Messaging"
#     description: ClassVar = "Message schema definition"


# @dataclass
# class PubsubPullSubscriptionNode(GCPNode):
#     ack_deadline_seconds:         int  = 20
#     filter:                       str  = ""
#     enable_message_ordering:      bool = False
#     enable_exactly_once_delivery: bool = False
#     service_account:              str  = ""
#     dead_letter_topic:            str  = ""
#     max_delivery_attempts:        int  = 5
#     minimum_backoff:              str  = "300s"
#     maximum_backoff:              str  = "600s"

#     params_schema: ClassVar = [
#         {"key": "ack_deadline_seconds", "label": "Ack Deadline (s)", "type": "number", "default": 20},
#         {"key": "filter", "label": "Filter Expression", "type": "text", "default": ""},
#         {"key": "enable_message_ordering", "label": "Message Ordering", "type": "boolean", "default": False},
#         {"key": "enable_exactly_once_delivery", "label": "Exactly Once Delivery", "type": "boolean", "default": False},
#         {"key": "service_account", "label": "Service Account Email", "type": "text", "default": ""},
#         {"key": "dead_letter_topic", "label": "Dead Letter Topic", "type": "text", "default": ""},
#     ]

#     inputs: ClassVar = [
#         Port("topic_link", PortType.SUBSCRIPTION, required=True),
#     ]
#     outputs: ClassVar = [] # Pull בד"כ נצרך ע"י Worker חיצוני
#     node_color:  ClassVar = "#ec485b"
#     icon:        ClassVar = "pubsub"
#     category:    ClassVar = "Messaging"
#     description: ClassVar = "Standard Pull Subscription"


# @dataclass
# class PubsubPushSubscriptionNode(GCPNode):
#     push_endpoint:              str = ""
#     ack_deadline_seconds:       int = 20
#     oidc_service_account_email: str = ""
#     audience:                   str = ""
#     expiration_policy:          str = "1209600s"
#     filter:                     str = ""

#     params_schema: ClassVar = [
#         {"key": "push_endpoint", "label": "Push Endpoint URL", "type": "text", "default": "", "placeholder": "https://..."},
#         {"key": "ack_deadline_seconds", "label": "Ack Deadline (s)", "type": "number", "default": 20},
#         {"key": "oidc_service_account_email", "label": "OIDC Service Account", "type": "text", "default": ""},
#         {"key": "audience", "label": "Audience", "type": "text", "default": ""},
#         {"key": "filter", "label": "Filter", "type": "text", "default": ""},
#     ]

#     inputs: ClassVar = [
#         Port("topic_link", PortType.SUBSCRIPTION, required=True),
#     ]
#     outputs: ClassVar = []
#     node_color:  ClassVar = "#ef4444"
#     icon:        ClassVar = "pubsub"
#     category:    ClassVar = "Messaging"
#     description: ClassVar = "Push Subscription to Webhook/Service"


# @dataclass
# class PubsubBigQuerySubscriptionNode(GCPNode):
#     table:               str  = ""
#     use_topic_schema:    bool = True
#     use_table_schema:    bool = False
#     write_metadata:      bool = False
#     drop_unknown_fields: bool = False

#     params_schema: ClassVar = [
#         {"key": "table", "label": "Target Table (project.dataset.table)", "type": "text", "default": ""},
#         {"key": "use_topic_schema", "label": "Use Topic Schema", "type": "boolean", "default": True},
#         {"key": "write_metadata", "label": "Write Metadata", "type": "boolean", "default": False},
#     ]

#     inputs: ClassVar = [
#         Port("topic_link", PortType.SUBSCRIPTION, required=True),
#     ]
#     outputs: ClassVar = [
#         Port("bq_table", PortType.DATABASE),
#     ]
#     node_color:  ClassVar = "#3b82f6"
#     icon:        ClassVar = "pubsub"
#     category:    ClassVar = "Messaging"
#     description: ClassVar = "BigQuery Push Subscription"


# @dataclass
# class PubsubCloudStorageSubscriptionNode(GCPNode):
#     bucket:                   str = ""
#     filename_prefix:          str = "log_events_"
#     filename_suffix:          str = ".avro"
#     filename_datetime_format: str = "YYYY-MM-DD/hh_mm_ssZ"
#     max_duration:             str = "60s"
#     max_bytes:                str = "10000000"
#     output_format:            str = "avro" # avro | text

#     params_schema: ClassVar = [
#         {"key": "bucket", "label": "GCS Bucket Name", "type": "text", "default": ""},
#         {"key": "filename_prefix", "label": "Prefix", "type": "text", "default": "log_events_"},
#         {"key": "output_format", "label": "Format", "type": "select", "options": ["avro", "text"], "default": "avro"},
#         {"key": "max_duration", "label": "Max Duration", "type": "text", "default": "60s"},
#     ]

#     inputs: ClassVar = [
#         Port("topic_link", PortType.SUBSCRIPTION, required=True),
#     ]
#     outputs: ClassVar = [
#         Port("gcs_bucket", PortType.STORAGE),
#     ]
#     node_color:  ClassVar = "#eab308"
#     icon:        ClassVar = "pubsub"
#     category:    ClassVar = "Messaging"
#     description: ClassVar = "Cloud Storage Push Subscription"


from dataclasses import dataclass, field
from typing import ClassVar
from nodes.base_node import GCPNode, Port
from nodes.port_types import PortType

# ── Messaging ─────────────────────────────────────────────────────────────────

@dataclass
class PubsubTopicNode(GCPNode):
    topic_name:                str  = ""
    message_retention_duration: str = "604800s"
    kms_key_name:               str = ""

    params_schema: ClassVar = [
        {"key": "topic_name", "label": "Topic Name", "type": "text", "default": "", "placeholder": "your topic name"},
        {"key": "message_retention_duration", "label": "Retention Duration", "type": "text", "default": "604800s"},
        {"key": "kms_key_name", "label": "KMS Key Name", "type": "text", "default": ""},
    ]

    inputs: ClassVar = [
        # גורמים שמפרסמים לטופיק (Cloud Run, Functions וכו')
        Port("publishers", PortType.TOPIC, multi_in=True),
    ]
    outputs: ClassVar = [
        # היציאה כעת היא מסוג SUBSCRIPTION כדי לחבר אליה צרכנים/סאבסקריפשנים
        Port("subscriptions", PortType.SUBSCRIPTION, multi=True),
    ]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Pub/Sub Topic - The core messaging hub"


@dataclass
class PubsubPullSubscriptionNode(GCPNode):
    ack_deadline_seconds:         int  = 20
    filter:                       str  = ""
    enable_message_ordering:      bool = False
    enable_exactly_once_delivery: bool = False
    service_account:              str  = ""
    dead_letter_topic:            str  = ""
    max_delivery_attempts:        int  = 5
    minimum_backoff:              str  = "300s"
    maximum_backoff:              str  = "600s"

    params_schema: ClassVar = [
        {"key": "ack_deadline_seconds", "label": "Ack Deadline (s)", "type": "number", "default": 20},
        {"key": "filter", "label": "Filter Expression", "type": "text", "default": ""},
        {"key": "enable_message_ordering", "label": "Message Ordering", "type": "boolean", "default": False},
        {"key": "enable_exactly_once_delivery", "label": "Exactly Once Delivery", "type": "boolean", "default": False},
        {"key": "service_account", "label": "Service Account Email", "type": "text", "default": ""},
        {"key": "dead_letter_topic", "label": "Dead Letter Topic", "type": "text", "default": ""},
    ]

    inputs: ClassVar = [
        Port("topic_link", PortType.SUBSCRIPTION, required=True),
    ]
    
    outputs: ClassVar = [
        Port("messages", PortType.MESSAGE, multi=True),
    ] # Pull בד"כ נצרך ע"י Worker חיצוני
    
    node_color:  ClassVar = "#ec485b"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Standard Pull Subscription"


@dataclass
class PubsubPushSubscriptionNode(GCPNode):
    push_endpoint:              str = ""
    ack_deadline_seconds:       int = 20
    oidc_service_account_email: str = ""
    audience:                   str = ""
    expiration_policy:          str = "1209600s"
    filter:                     str = ""

    params_schema: ClassVar = [
        {"key": "push_endpoint", "label": "Push Endpoint URL", "type": "text", "default": "", "placeholder": "https://..."},
        {"key": "ack_deadline_seconds", "label": "Ack Deadline (s)", "type": "number", "default": 20},
        {"key": "oidc_service_account_email", "label": "OIDC Service Account", "type": "text", "default": ""},
        {"key": "audience", "label": "Audience", "type": "text", "default": ""},
        {"key": "filter", "label": "Filter", "type": "text", "default": ""},
    ]

    inputs: ClassVar = [
        Port("topic_link", PortType.SUBSCRIPTION, required=True),
    ]
    outputs: ClassVar = [
        Port("messages", PortType.MESSAGE, multi=True),
    ] 
    
    node_color:  ClassVar = "#ef4444"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Push Subscription to Webhook/Service"


@dataclass
class PubsubBigQuerySubscriptionNode(GCPNode):
    table:               str  = ""
    use_topic_schema:    bool = True
    use_table_schema:    bool = False
    write_metadata:      bool = False
    drop_unknown_fields: bool = False

    params_schema: ClassVar = [
        {"key": "table", "label": "Target Table (project.dataset.table)", "type": "text", "default": ""},
        {"key": "use_topic_schema", "label": "Use Topic Schema", "type": "boolean", "default": True},
        {"key": "write_metadata", "label": "Write Metadata", "type": "boolean", "default": False},
    ]

    inputs: ClassVar = [
        Port("topic_link", PortType.SUBSCRIPTION, required=True),
    ]
    outputs: ClassVar = [
        Port("bq_table", PortType.DATABASE),
    ]
    node_color:  ClassVar = "#3b82f6"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "BigQuery Push Subscription"


@dataclass
class PubsubCloudStorageSubscriptionNode(GCPNode):
    bucket:                   str = ""
    filename_prefix:          str = "log_events_"
    filename_suffix:          str = ".avro"
    filename_datetime_format: str = "YYYY-MM-DD/hh_mm_ssZ"
    max_duration:             str = "60s"
    max_bytes:                str = "10000000"
    output_format:            str = "avro" # avro | text

    params_schema: ClassVar = [
        {"key": "bucket", "label": "GCS Bucket Name", "type": "text", "default": ""},
        {"key": "filename_prefix", "label": "Prefix", "type": "text", "default": "log_events_"},
        {"key": "output_format", "label": "Format", "type": "select", "options": ["avro", "text"], "default": "avro"},
        {"key": "max_duration", "label": "Max Duration", "type": "text", "default": "60s"},
    ]

    inputs: ClassVar = [
        Port("topic_link", PortType.SUBSCRIPTION, required=True),
    ]
    outputs: ClassVar = [
        Port("gcs_bucket", PortType.STORAGE),
    ]
    node_color:  ClassVar = "#eab308"
    icon:        ClassVar = "pubsub"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Cloud Storage Push Subscription"