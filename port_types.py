from enum import Enum


class PortType(Enum):
    SERVICE_ACCOUNT = "service_account"
    NETWORK         = "network"
    STORAGE         = "storage"
    SECRET          = "secret"
    TOPIC           = "topic"
    DATABASE        = "database"


PORT_META: dict[str, dict] = {
    PortType.SERVICE_ACCOUNT.value: {"color": "#a78bfa", "label": "SA"},
    PortType.NETWORK.value:         {"color": "#34d399", "label": "Net"},
    PortType.STORAGE.value:         {"color": "#fbbf24", "label": "GCS"},
    PortType.SECRET.value:          {"color": "#f472b6", "label": "Sec"},
    PortType.TOPIC.value:           {"color": "#60a5fa", "label": "Topic"},
    PortType.DATABASE.value:        {"color": "#fb923c", "label": "DB"},
}
