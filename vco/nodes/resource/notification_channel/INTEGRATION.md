# NotificationChannelNode — Integration Checklist

## 1. העתק את התיקייה
```
cp -r notification_channel/ vco/nodes/resource/notification_channel/
```

## 2. הוסף PortType.NOTIFICATION ל-port_types.py
```python
# nodes/port_types.py — הוסף לתוך ה-Enum:
NOTIFICATION = "notification"
```

## 3. הוסף NOTIFICATION port לכל resource node שרוצים לחבר
כל node שאתה רוצה שיוכל להחבר ל-NotificationChannelNode צריך port output מסוג NOTIFICATION.

### GcsBucketNode
```python
outputs: ClassVar = [
    Port("storage",       PortType.STORAGE,       multi=True),
    Port("notification",  PortType.NOTIFICATION,  multi=True, label="notify"),  # ← חדש
]
```

### CloudRunNode
```python
outputs: ClassVar = [
    Port("http",          PortType.HTTP_TARGET,   multi=True),
    Port("notification",  PortType.NOTIFICATION,  multi=True, label="notify"),  # ← חדש
]
```

### PubsubTopicNode
```python
outputs: ClassVar = [
    Port("topic",         PortType.TOPIC,         multi=True),
    Port("notification",  PortType.NOTIFICATION,  multi=True, label="notify"),  # ← חדש
]
```

### CloudFunctionsNode
```python
outputs: ClassVar = [
    ...existing ports...,
    Port("notification",  PortType.NOTIFICATION,  multi=True, label="notify"),  # ← חדש
]
```

### BigQueryNode
```python
outputs: ClassVar = [
    ...existing ports...,
    Port("notification",  PortType.NOTIFICATION,  multi=True, label="notify"),  # ← חדש
]
```

### CloudSqlNode, CloudSchedulerNode, WorkflowNode — אותו דבר

---

## 4. איך זה עובד ב-UI

```
[GcsBucketNode] ──notification──► [NotificationChannelNode]
                                         channel_type = email
                                         email_address = ops@company.com

→ Pulumi יוצר:
    google_monitoring_notification_channel (email)
  + google_storage_notification (OBJECT_FINALIZE on the bucket)
    OR google_monitoring_alert_policy עם filter על ה-bucket
```

```
[CloudRunNode] ──notification──► [NotificationChannelNode]
                                        channel_type = slack
                                        slack_channel = #prod-alerts

→ Pulumi יוצר:
    google_monitoring_notification_channel (slack)
  + google_monitoring_alert_policy (5xx error rate > 0 on the Cloud Run service)
```

---

## 5. DAG order

ה-NotificationChannelNode תמיד מחכה לסורס node להתפרס קודם (dag_deps מחזיר את source_id),
כי הוא צריך את ה-resource name מ-deployed_outputs.

---

## 6. סיכום הפורטים לפי ה-source

| Source Node        | PortType שצריך להוסיף | מה Pulumi יוצר                        |
|--------------------|----------------------|---------------------------------------|
| GcsBucketNode      | NOTIFICATION (out)   | storage.Notification + AlertPolicy    |
| PubsubTopicNode    | NOTIFICATION (out)   | AlertPolicy (message_count)           |
| CloudRunNode       | NOTIFICATION (out)   | AlertPolicy (5xx rate)                |
| CloudFunctionsNode | NOTIFICATION (out)   | AlertPolicy (error count)             |
| BigQueryNode       | NOTIFICATION (out)   | AlertPolicy (slot utilization)        |
| CloudSqlNode       | NOTIFICATION (out)   | AlertPolicy (disk utilization)        |
| CloudSchedulerNode | NOTIFICATION (out)   | AlertPolicy (job failure)             |
| WorkflowNode       | NOTIFICATION (out)   | AlertPolicy (execution failure)       |
