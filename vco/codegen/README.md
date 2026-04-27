# VCO Node Codegen

מערכת דו-שלבית לגנרציה אוטומטית של node-ים מתוך ה-Pulumi GCP schema.

## מבנה קבצים

```
codegen/
├── schema_to_nodes.py      # Phase 1 — קורא schema, מייצר קבצי .py
├── run.sh                  # wrapper נוח לכל הפקודות
├── schema.json             # cache של pulumi package get-schema gcp (נוצר אוטומטית)
├── templates/
│   └── node_template.py.j2 # Jinja2 template לקובץ הסופי
└── overlays/
    ├── _defaults.yaml      # ברירות מחדל גלובליות
    ├── _TEMPLATE.yaml      # תבנית ריקה להעתקה
    ├── cloudrunv2_service.yaml
    ├── cloudrunv2_job.yaml
    └── workflows_workflow.yaml
```

## שימוש מהיר

```bash
# הפעם הראשונה (מוריד את ה-schema)
./codegen/run.sh --refresh-schema

# גנרציה של כל ה-resources שיש להם overlay
./codegen/run.sh

# גנרציה של resource ספציפי
./codegen/run.sh cloudrunv2.Service

# תצוגה מקדימה בלבד (לא כותב קבצים)
./codegen/run.sh --dry-run
```

---

## איך להוסיף resource חדש

### שלב 1 — מצא את שם ה-type ב-Pulumi

```bash
# חפש בתוך ה-schema
cat codegen/schema.json | python -c "
import json,sys
s=json.load(sys.stdin)
q='pubsub'   # ← שנה לחיפוש שלך
for k in s['resources']:
    if q in k.lower(): print(k)
"
```

הפורמט הוא: `gcp:MODULE/resource:Resource`  
ה-`pulumi_type` שמזינים לסקריפט הוא: `MODULE.Resource`  
לדוגמה: `pubsub.Topic`, `storage.Bucket`, `bigquery.Dataset`

### שלב 2 — צור overlay YAML

```bash
cp codegen/overlays/_TEMPLATE.yaml codegen/overlays/pubsub_topic.yaml
```

ערוך את הקובץ — הוסף רק את מה שאתה צריך לשלוט בו:

```yaml
class_name:  PubsubTopicNode
description: Pub/Sub message topic
category:    Messaging
node_color:  "#a78bfa"
icon:        pubsub

params_schema:
  - key: message_retention_duration
    label: Message Retention
    type: text
    default: "86400s"

inputs:
  - name: schema
    port_type: SCHEMA
    required: false

outputs:
  - name: subscription
    port_type: TOPIC
    multi: true

resolve_edges_body: |
        if src_id == self.node_id and tgt_type == "PubsubSubscriptionNode":
            ctx[tgt_id].setdefault("topic_id", self.node_id)
            return True
        return False

log_source_body: |
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=f'resource.type="pubsub_topic" AND resource.labels.topic_id="{name}"',
            project=project,
        )
```

### שלב 3 — הרץ את ה-codegen

```bash
./codegen/run.sh pubsub.Topic
```

זה מייצר: `nodes/pubsub_topic.py`

ה-registry מגלה אותו אוטומטית — אין צורך לרשום אותו בשום מקום.

---

## מה נשאר ידני?

| מה | איפה |
|---|---|
| הגדרת ports | `overlays/<resource>.yaml` → `inputs` / `outputs` |
| לוגיקת edge wiring | `overlays/<resource>.yaml` → `resolve_edges_body` |
| תלויות deploy | `overlays/<resource>.yaml` → `dag_deps_body` |
| הגדרת Pulumi resource | `overlays/<resource>.yaml` → `extra_methods` (override `pulumi_program`) |
| log streaming filter | `overlays/<resource>.yaml` → `log_source_body` |

## מה מגיע אוטומטית מה-schema?

- כל ה-`inputProperties` של ה-resource הופכים ל-`params_schema` entries
- מיפוי אוטומטי של טיפוסי שדות: `string→text`, `integer→number`, `enum→select`
- תיאורים מה-schema מוסיפים `description` לכל פרמטר
- שם הקלאס וה-Pulumi module/class נגזרים אוטומטית

---

## Overlay keys — reference מלא

| key | חובה | תיאור |
|---|---|---|
| `class_name` | ✅ | שם הקלאס Python |
| `description` | ✅ | תיאור קצר |
| `category` | ✅ | קטגוריית sidebar |
| `node_color` | ✅ | צבע hex |
| `icon` | ✅ | שם האייקון |
| `url_field` | ❌ | prop key להצגה כ-URL |
| `params_schema` | ❌ | params ידניים (נוספים לאוטומטיים) |
| `inputs` | ❌ | רשימת input ports |
| `outputs` | ❌ | רשימת output ports |
| `resolve_edges_body` | ❌ | גוף ה-method (Python, indent 8) |
| `dag_deps_body` | ❌ | גוף ה-method (Python, indent 8) |
| `pulumi_program_extra` | ❌ | קוד לפני `def program()` |
| `live_outputs_body` | ❌ | גוף ה-method (Python, indent 8) |
| `log_source_body` | ❌ | גוף ה-method (Python, indent 8) |
| `extra_methods` | ❌ | methods שלמים (Python, indent 4) — override של `pulumi_program` |