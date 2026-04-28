# VCO Node Codegen

מערכת אוטומטית לייצור node-ים מתוך ה-Pulumi GCP schema.

---

## מבנה קבצים

```
project/
├── codegen/
│   ├── schema_to_nodes.py        ← קודג'ן ראשי (Phase 1+2)
│   ├── triage.py                 ← סינון resources מהסכמה
│   ├── run.sh                    ← wrapper נוח לכל הפקודות
│   ├── schema.json               ← cache של pulumi schema (נוצר אוטומטית)
│   ├── resources.txt             ← רשימת resources שנבחרו
│   ├── resources_report.txt      ← דוח סינון לפי module
│   ├── templates/
│   │   └── node_template.py.j2   ← Jinja2 template לקובץ הסופי
│   └── overlays/
│       ├── _defaults.yaml        ← ברירות מחדל גלובליות
│       ├── _TEMPLATE.yaml        ← תבנית ריקה להעתקה
│       ├── cloudrunv2_service.yaml
│       ├── cloudrunv2_job.yaml
│       ├── workflows_workflow.yaml
│       └── … overlays נוספים
└── nodes/
    ├── cloudrunv2_service.py     ← נוצר אוטומטית
    ├── cloudrunv2_job.py
    └── … קבצי Python נוצרים כאן
```

**כותבים ידנית:** `schema_to_nodes.py`, `triage.py`, `run.sh`, `templates/`, `overlays/`
**נוצר אוטומטית:** כל קובץ ב-`nodes/`

---

## הרצה — פעם ראשונה

### שלב 0 — התקנת תלויות

```bash
pip install jinja2 pyyaml
```

### שלב 1 — הורדת ה-schema מ-Pulumi

```bash
pulumi package get-schema gcp > codegen/schema.json
```

> לוקח ~30 שניות. מייצר קובץ של ~50MB עם ~1,000 resources.

### שלב 2 — סינון: אילו resources שווים כ-nodes

```bash
python codegen/triage.py \
    --schema  codegen/schema.json \
    --out     codegen/resources.txt \
    --report  codegen/resources_report.txt
```

מייצר:
- `resources.txt` — רשימת resources שעברו סינון (אחד לשורה)
- `resources_report.txt` — דוח מפורט לפי module

### שלב 3 — קודג'ן: ייצור קבצי Python

```bash
python codegen/schema_to_nodes.py \
    --schema    codegen/schema.json \
    --overlays  codegen/overlays/ \
    --templates codegen/templates/ \
    --out       nodes/ \
    --resources $(cat codegen/resources.txt | tr '\n' ' ')
```

מייצר קובץ `.py` אחד ב-`nodes/` לכל resource.

---

## קיצורי דרך — `run.sh`

```bash
# פעם ראשונה — מוריד schema ומריץ הכל
./codegen/run.sh --refresh-schema

# הרצה רגילה (schema כבר קיים)
./codegen/run.sh

# resource ספציפי בלבד
./codegen/run.sh cloudrunv2.Service

# תצוגה מקדימה בלי לכתוב קבצים
./codegen/run.sh --dry-run
```

---

## הרצה חוזרת (אחרי שינויים)

| מה השתנה | מה מריצים |
|---|---|
| שינוי overlay קיים | `./codegen/run.sh cloudrunv2.Service` |
| הוספת overlay חדש | `./codegen/run.sh pubsub.Topic` |
| עדכון ה-schema (גרסה חדשה של Pulumi) | `./codegen/run.sh --refresh-schema` |
| שינוי ב-template | `./codegen/run.sh` (מריץ על כולם) |
| שינוי ב-triage (חוקי סינון) | `python codegen/triage.py ...` ואז `./codegen/run.sh` |

---

## כשמוסיפים resource חדש

### שלב 1 — מצא את שם ה-type

```bash
# חפש בדוח הסינון
grep -i "pubsub" codegen/resources_report.txt

# או חפש ישירות בסכמה
python -c "
import json
schema = json.load(open('codegen/schema.json'))
for k in schema['resources']:
    if 'pubsub' in k.lower(): print(k)
"
```

פורמט בסכמה: `gcp:MODULE/resource:Resource`
ה-`pulumi_type` שמזינים לסקריפט: `MODULE.Resource`

דוגמאות:
```
gcp:pubsub/topic:Topic        →  pubsub.Topic
gcp:storage/bucket:Bucket     →  storage.Bucket
gcp:bigquery/dataset:Dataset  →  bigquery.Dataset
```

### שלב 2 — צור overlay

```bash
cp codegen/overlays/_TEMPLATE.yaml codegen/overlays/pubsub_topic.yaml
```

ערוך — כתוב רק את מה שאתה רוצה לשלוט בו:

```yaml
class_name:  PubsubTopicNode
description: Pub/Sub message topic
category:    Messaging
node_color:  "#f59e0b"
icon:        pubsub

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

> אם אין overlay — נוצר קובץ בסיסי עובד עם `name` + `project` בלבד.

### שלב 3 — הרץ

```bash
./codegen/run.sh pubsub.Topic
# → מייצר: nodes/pubsub_topic.py
```

---

## מפתח overlay keys

| key | חובה | תיאור |
|---|---|---|
| `class_name` | ✅ | שם קלאס Python — חייב להסתיים ב-`Node` |
| `description` | ✅ | תיאור קצר |
| `category` | ✅ | ראה רשימה מטה |
| `node_color` | ✅ | hex color |
| `icon` | ✅ | שם אייקון |
| `url_field` | ❌ | prop key שמוצג כ-URL לחיץ (למשל `service_url`) |
| `params_schema` | ❌ | params ידניים — מוכנסים לפני האוטומטיים מהסכמה |
| `inputs` | ❌ | input ports |
| `outputs` | ❌ | output ports |
| `resolve_edges_body` | ❌ | גוף `resolve_edges()` — Python, dedented |
| `dag_deps_body` | ❌ | גוף `dag_deps()` — Python, dedented |
| `live_outputs_body` | ❌ | גוף `live_outputs()` — Python, dedented |
| `log_source_body` | ❌ | גוף `log_source()` — Python, dedented |
| `pulumi_program_method` | ❌ | `def pulumi_program(...)` שלם — **מחליף** את ה-skeleton |
| `extra_class_members` | ❌ | class vars, `@staticmethod` — מוכנסים בסוף הקלאס |

### ערכי category

```
Compute  Messaging  Storage  Orchestration  Security
Networking  Integration_Services  AI_ML  Operations  DevOps  General
```

### ערכי PortType

```
SERVICE_ACCOUNT  NETWORK    HTTP_TARGET  TASK_QUEUE
SECRET           MESSAGE    TOPIC        STORAGE
RUN_JOB          SUBSCRIPTION  EVENT     SCHEMA
```

---

## כללי כתיבת body keys

כל body key נכתב כ-YAML block scalar (`|`) — indent יחסי, ה-template מטפל בכל השאר:

```yaml
# נכון ✅
resolve_edges_body: |
  if src_id == self.node_id:
      ctx[self.node_id].setdefault("list", []).append(tgt_id)
      return True
  return False
```

---

## מה `triage.py` מסנן

| כלל | דוגמאות שהוצאו |
|---|---|
| Module לא ברשימה | `apigee`, `billing`, `accesscontextmanager` |
| סיומת `IamBinding/Member/Policy` | `cloudrunv2.ServiceIamBinding` |
| `compute` לא ב-allow-list | `compute.RegionCommitment`, `compute.ProjectMetadata` |
| פחות מ-2 props שימושיים | resources ריקים מדי |
| `deprecated` ב-description | כל resource deprecated |

לשינוי חוקי הסינון — ערוך `INCLUDE_MODULES`, `EXCLUDE_SUFFIXES`, `COMPUTE_ALLOW` ב-`triage.py`.

---

## שגיאות נפוצות

| שגיאה | פתרון |
|---|---|
| `Schema not found` | הרץ `pulumi package get-schema gcp > codegen/schema.json` |
| `not in schema — skipped` | בדוק את שם ה-type ב-`resources_report.txt` |
| `SyntaxError` בקובץ שנוצר | בדוק indentation ב-overlay — השתמש ב-`| ` ולא `>` |
| `StrictUndefined` ב-Jinja | גרסה ישנה של `schema_to_nodes.py` — עדכן |