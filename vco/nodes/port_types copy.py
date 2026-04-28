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
    # ── Existing ──────────────────────────────────────────────────────────────
    HTTP_TARGET         = "http_target"   # Scheduler / Tasks / Workflows → CR
    TASK_QUEUE          = "task_queue"    # CloudTasksQueue → consumers
    WORKFLOW            = "workflow"      # Workflow → callee / chaining
    EVENT               = "event"         # Eventarc trigger → CloudRun
    BUCKET              = "bucket"        # GCS Bucket ↔ Eventarc / CloudRun
    RUN_JOB             = "run_job"       # Scheduler → CloudRunJob trigger
    # ── New ───────────────────────────────────────────────────────────────────
    DIRECT_EVENT        = "direct_event"  # Firestore / RTDB / Build / GCS → DirectEventTriggerNode


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
    # ── Existing ──────────────────────────────────────────────────────────────
    PortType.HTTP_TARGET.value:     {"color": "#38bdf8", "label": "HTTP"},
    PortType.TASK_QUEUE.value:      {"color": "#fb7185", "label": "Queue"},
    PortType.WORKFLOW.value:        {"color": "#c084fc", "label": "WF"},
    PortType.EVENT.value:           {"color": "#f97316", "label": "Event"},
    PortType.BUCKET.value:          {"color": "#facc15", "label": "Bucket"},
    PortType.RUN_JOB.value:         {"color": "#a5b4fc", "label": "Job"},
    # ── New ───────────────────────────────────────────────────────────────────
    PortType.DIRECT_EVENT.value:    {"color": "#8b5cf6", "label": "Direct"},
}