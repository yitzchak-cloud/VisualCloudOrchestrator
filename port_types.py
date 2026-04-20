from enum import Enum


class PortType(Enum):
    SERVICE_ACCOUNT     = "service_account"
    NETWORK             = "network"
    STORAGE             = "storage"
    SECRET              = "secret"
    TOPIC               = "topic"
    DATABASE            = "database"
    SUBSCRIPTION        = "subscription"
    SCHEMA              = "schema"
    MESSAGE             = "message"


PORT_META: dict[str, dict] = {
    PortType.SERVICE_ACCOUNT.value: {"color": "#a78bfa", "label": "SA"},
    PortType.NETWORK.value:         {"color": "#34d399", "label": "Net"},
    PortType.STORAGE.value:         {"color": "#fbbf24", "label": "GCS"},
    PortType.SECRET.value:          {"color": "#f472b6", "label": "Sec"},
    PortType.TOPIC.value:           {"color": "#60a5fa", "label": "Topic"},
    PortType.SUBSCRIPTION.value:    {"color": "#1523bd", "label": "Sub"},
    PortType.DATABASE.value:        {"color": "#fb923c", "label": "DB"},
    PortType.SCHEMA.value:          {"color": "#8b5cf6", "label": "Schema"},
    PortType.MESSAGE.value:         {"color": "#ec4899", "label": "Msg"},
}
