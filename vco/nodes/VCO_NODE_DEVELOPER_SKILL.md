# VCO Node Developer Skill
> הנחיות מלאות לייצור משאב (node) חדש במערכת VCO.  
> עקוב בדיוק — אין צורך בשום קובץ נוסף.

---

## 1. מבנה תיקיות

```
nodes/resource/<node_name>/
├── __init__.py
├── <node_name>.py            ← class ראשי
├── <node_name>_params.yaml   ← כל פרמטרי ה-UI
├── _pulumi.py                ← לוגיקת Pulumi (אם הקובץ הראשי > ~150 שורות)
├── _terraform.py             ← לוגיקת Terraform (אם הקובץ הראשי > ~150 שורות)
└── terraform/
    ├── main.tf
    ├── variables.tf
    └── outputs.tf
```

**כלל:** אם הנוד פשוט (<150 שורות) — שים הכל בקובץ הראשי.  
**כלל:** אם מורכב — פצל ל-`_pulumi.py` + `_terraform.py` ובצע import מהקובץ הראשי.

---

## 2. `__init__.py`

```python
from .<node_name> import <NodeClassName>

__all__ = ["<NodeClassName>"]
```

---

## 3. קובץ הנוד הראשי — תבנית מלאה

```python
"""
nodes/resource/<node_name>/<node_name>.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class <NodeClassName>(GCPNode):
    """תיאור קצר של המשאב."""

    # ── params_schema ──────────────────────────────────────────────────────────
    # אפשרות א: inline (נוד פשוט)
    params_schema: ClassVar = [
        {"key": "name",   "label": "Name",   "type": "text",   "default": "", "category": "Basic"},
        {"key": "region", "label": "Region", "type": "select", "default": "us-central1",
         "options": ["us-central1", "europe-west1"], "category": "Basic"},
    ]

    # אפשרות ב: טעינה מ-YAML (נוד מורכב — base_node טוען אוטומטית)
    # שים קובץ <node_name>_params.yaml באותה תיקייה — params_schema יוטען אוטומטית.
    # אם רוצים לטעון ידנית (כדי לאפשר show_if וכו'):
    # params_schema: ClassVar = _load_params()   # ראה סעיף 4

    # ── Ports ──────────────────────────────────────────────────────────────────
    inputs:  ClassVar = [Port("input_port_name",  PortType.TOPIC,        required=True)]
    outputs: ClassVar = [Port("output_port_name", PortType.MESSAGE,      multi=True)]
    # multi=True  → ניתן לחבר כמה edges יוצאים
    # multi=False → edge יוצא אחד בלבד
    # multi_in=True → ניתן לחבר כמה edges נכנסים
    # required=True → חובה לחבר לפני deploy

    # ── Metadata (מוצג ב-UI) ──────────────────────────────────────────────────
    node_color:  ClassVar = "#3b82f6"   # צבע hex לכרטיס
    icon:        ClassVar = "pubsub"    # שם קובץ SVG ב-/icons/
    category:    ClassVar = "Messaging" # קטגוריה בפאלט
    description: ClassVar = "תיאור הנוד שמוצג ב-UI"
    url_field:   ClassVar = None        # מפתח prop שמוצג כקישור — לדוג' "uri"

    # ══════════════════════════════════════════════════════════════════════════
    # Edge wiring
    # ══════════════════════════════════════════════════════════════════════════

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        """
        נקרא עבור כל edge בגרף.
        ctx[node_id] הוא dict שמצטבר — שמור בו מה שתצטרך ב-pulumi_program.
        החזר True אם ה-edge שייך לנוד הזה, False אחרת.
        """
        # דוגמה: הנוד הזה הוא TARGET — מישהו מתחבר אליו
        if tgt_id == self.node_id:
            ctx[self.node_id].setdefault("source_ids", []).append(src_id)
            return True
        # דוגמה: הנוד הזה הוא SOURCE — הוא מתחבר למישהו
        if src_id == self.node_id:
            ctx[tgt_id]["parent_id"] = self.node_id
            return True
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # DAG dependencies
    # ══════════════════════════════════════════════════════════════════════════

    def dag_deps(self, ctx) -> list[str]:
        """
        מחזיר רשימת node_id שחייבים להיות deployed לפני הנוד הזה.
        הסדר נקבע לפי זה — אל תחזיר circular deps.
        """
        deps = []
        if ctx.get("parent_id"):
            deps.append(ctx["parent_id"])
        return deps

    # ══════════════════════════════════════════════════════════════════════════
    # Pulumi program
    # ══════════════════════════════════════════════════════════════════════════

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        """
        מחזיר callable שיוצר את המשאב ב-GCP דרך Pulumi.
        מחזיר None אם dependency חסר (הנוד יידלג).

        deployed_outputs[node_id] = dict עם outputs של נוד שכבר deployed.
        לדוגמה: deployed_outputs[topic_id].get("name")
        """
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        # בדיקת dependency
        parent_name = deployed_outputs.get(ctx.get("parent_id", ""), {}).get("name", "")
        if not parent_name:
            logger.warning("%s: parent not deployed — skipping", self.node_id)
            return None

        def program() -> None:
            resource = gcp.some_service.Resource(
                self.node_id,
                name=_resource_name(node_dict),
                parent=parent_name,
                some_prop=props.get("some_prop", "default"),
                project=project,
            )
            # חובה: export name ו-id לפחות
            pulumi.export("name", resource.name)
            pulumi.export("id",   resource.id)
            # אופציונלי: כל output שתרצה
            pulumi.export("uri",  resource.uri)

        return program

    # ══════════════════════════════════════════════════════════════════════════
    # Terraform
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def terraform_instance_prefix(self) -> str:
        """prefix לשם ה-module ב-Terraform. ייצר: module.<prefix>_<tf_name>"""
        return "my_resource"

    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict:
        """
        מחזיר dict של משתנים להעביר ל-Terraform module.
        ערכים חייבים להיות מחרוזות מוכנות ל-HCL.
        """
        from nodes.base_node import _resource_name, _tf_name, _node_by_id
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})

        cv = {
            "name":     f'"{_resource_name(node_dict)}"',
            "location": f'"{props.get("region", region)}"',
        }

        parent_id = ctx.get("parent_id", "")
        if parent_id:
            cv["parent_name"] = f"module.topic_{_tf_name(_node_by_id(all_nodes, parent_id))}.name"
        else:
            cv["parent_name"] = '""'

        # bool
        cv["enabled"] = "true" if props.get("enabled") else "false"

        # optional string
        if props.get("filter", "").strip():
            cv["filter"] = f'"{props["filter"].strip()}"'

        return cv

    # ══════════════════════════════════════════════════════════════════════════
    # Live outputs & logging
    # ══════════════════════════════════════════════════════════════════════════

    def live_outputs(self, pulumi_outputs, project, region) -> dict:
        """
        מה מוצג ב-UI אחרי deploy.
        המפתחות מוצגים ליד הנוד בקנבס.
        """
        return {
            "name": pulumi_outputs.get("name", ""),
            "uri":  pulumi_outputs.get("uri",  ""),
        }

    def log_source(self, pulumi_outputs, project, region) -> LogSource | None:
        """
        מגדיר Cloud Logging filter עבור כפתור ה-logs ב-UI.
        מחזיר None אם אין logs רלוונטיים.
        """
        name = pulumi_outputs.get("name", "")
        if not name:
            return None
        return LogSource(
            filter=(
                f'resource.type="my_resource_type"'
                f' AND resource.labels.resource_id="{name}"'
            ),
            project=project,
        )
```

---

## 4. `<node_name>_params.yaml` — כל אפשרויות ה-UI

```yaml
# ── קטגוריה ──────────────────────────────────────────────────────────────────
- key: field_key          # מפתח ב-props
  label: Field Label      # תווית ב-UI
  type: text              # ראה סוגי שדות למטה
  default: ""
  placeholder: "hint..."  # אופציונלי
  category: Basic         # קטגוריה לקיבוץ (Basic / Advanced / Security / ...)
  description: >          # טקסט tooltip — מופיע כ-? ליד השדה
    תיאור מפורט של השדה.
    יכול להיות מספר שורות.

# ── סוגי שדות ─────────────────────────────────────────────────────────────────

# text — שדה חופשי
- key: name
  label: Name
  type: text
  default: ""
  placeholder: my-resource

# number — מספר
- key: port
  label: Port
  type: number
  default: 8080

# checkbox — true/false
- key: enabled
  label: Enabled
  type: checkbox
  default: true

# select — dropdown
- key: region
  label: Region
  type: select
  default: us-central1
  options:
    - us-central1
    - us-east1
    - europe-west1
    - asia-east1

# yaml / json / code — editor מלא
- key: config
  label: Config
  type: yaml
  default: ""

# ── show_if — הצג שדה רק כשתנאי מתקיים ────────────────────────────────────
# חשוב: show_if נמחק על-ידי base_node בסריאליזציה לקליינט.
# יש להוסיף client-side patch (ראה סעיף 7).
- key: push_endpoint
  label: Push Endpoint
  type: text
  default: ""
  category: Push Options
  show_if:
    subscription_type: push   # מוצג רק כש-props.subscription_type === "push"

# ── cascade_parent — options תלויות בשדה אחר ──────────────────────────────
- key: machine_type
  label: Machine Type
  type: select
  default: ""
  cascade_parent: region
  catalog:
    us-central1: [n1-standard-1, n1-standard-2, n2-standard-2]
    europe-west1: [n1-standard-1, n1-standard-4]

# ── auto_from_port — נעול לערך שמגיע מ-edge מחובר ────────────────────────
- key: provider
  label: Provider
  type: select
  default: google
  auto_from_port: source   # שם ה-input port שממנו לקחת את הערך
```

---

## 5. PortType — כל הסוגים

```python
from nodes.port_types import PortType

PortType.TOPIC        # יציאה מ-Topic, כניסה ל-Subscription
PortType.SUBSCRIPTION # יציאה מ-Subscription, כניסה ל-Consumer
PortType.MESSAGE      # הודעות — כניסה ל-Cloud Run וכו'
PortType.HTTP         # HTTP endpoint
PortType.SERVICE      # service-to-service
PortType.STORAGE      # GCS / bucket
PortType.DATABASE     # SQL / Firestore
PortType.SECRET       # Secret Manager
PortType.IAM          # IAM / Service Account
```

**Port signature:**
```python
Port(
    name: str,           # שם ה-handle ב-UI ובedge
    type: PortType,      # סוג — חייב להתאים בין source ל-target
    multi: bool = True,  # output: האם אפשר כמה edges יוצאים
    multi_in: bool = False, # input: האם אפשר כמה edges נכנסים
    required: bool = False, # האם חייב להיות מחובר
)
```

---

## 6. Terraform — שלושת הקבצים

### `terraform/variables.tf`
```hcl
variable "name" {
  description = "Resource name"
  type        = string
}

variable "location" {
  description = "GCP region or zone"
  type        = string
  default     = "us-central1"
}

variable "enabled" {
  description = "Whether the resource is enabled"
  type        = bool
  default     = true
}

variable "parent_name" {
  description = "Parent resource name (empty = not set)"
  type        = string
  default     = ""
}

# optional — only pass if non-empty
variable "filter" {
  description = "Filter expression"
  type        = string
  default     = ""
}
```

### `terraform/main.tf`
```hcl
resource "google_some_resource" "main" {
  name     = var.name
  location = var.location
  project  = var.project_id   # project_id מועבר אוטומטית מה-caller

  # optional fields with conditional
  filter = var.filter != "" ? var.filter : null

  # reference to parent module output
  parent = var.parent_name != "" ? var.parent_name : null
}
```

### `terraform/outputs.tf`
```hcl
output "name" {
  description = "Resource name"
  value       = google_some_resource.main.name
}

output "id" {
  description = "Resource ID"
  value       = google_some_resource.main.id
}

# optional
output "uri" {
  description = "Resource URI"
  value       = google_some_resource.main.uri
}
```

---

## 7. show_if — Client-side patch (חובה אם משתמשים ב-show_if)

`base_node.__init_subclass__` מסדרל רק שדות בסיסיים ומוחק `show_if`.  
יש להוסיף את ה-`show_if` בחזרה בקוד ה-JS של `indxe.html`, בתוך אתחול הטעינה:

```javascript
// בתוך useEffect שטוען את /api/node-types — אחרי setNodeTypesData(typesData):

const MY_NODE_SHOW_IF = {
  field_only_when_type_a: { mode: "type_a" },
  field_only_when_type_b: { mode: "type_b" },
};

// patch את ה-typesData לפני setNodeTypesData
const patchedTypes = (typesData || []).map(t => {
  if (t.type !== "MyNodeClassName") return t;
  return {
    ...t,
    params_schema: (t.params_schema || []).map(f =>
      MY_NODE_SHOW_IF[f.key]
        ? { ...f, show_if: MY_NODE_SHOW_IF[f.key] }
        : f
    ),
  };
});
if (patchedTypes?.length) setNodeTypesData(patchedTypes);
```

---

## 8. Dynamic ports — פורטים שמשתנים לפי prop

כשהנוד צריך פורטים שונים לפי ערך prop (למשל pull/push):

### Python
```python
@dataclass
class MyNode(GCPNode):
    outputs: ClassVar = [Port("out", PortType.MESSAGE, multi=True)]  # default

    def get_outputs(self) -> list[Port]:
        """נקרא על-ידי base_node לקבל פורטים live."""
        mode = getattr(self, "_props", {}).get("mode", "default")
        if mode == "single":
            return [Port("out", PortType.MESSAGE, multi=False)]
        return [Port("out", PortType.MESSAGE, multi=True)]

    def pulumi_program(self, ctx, ...):
        self._props = ctx.get("node", {}).get("props", {})
        ...
```

### JavaScript (`indxe.html` — בתוך `handlePropChange`)
```javascript
// הוסף בתוך setNodes map — לפני ה-return:
if (isProp && key === "mode" && n.data.schema?.type === "MyNodeClassName") {
  const newOutputs = value === "single"
    ? [{ name: "out", type: "message", multi: false, label: "out" }]
    : [{ name: "out", type: "message", multi: true,  label: "out" }];
  updatedSchema = { ...n.data.schema, outputs: newOutputs };
}
```

### JavaScript — ניקוי edges ישנים כשעוברים ל-single
```javascript
if (isProp && key === "mode" && value === "single") {
  setEdges(eds => {
    const outgoing = eds.filter(e => e.source === nodeId && e.sourceHandle === "out");
    if (outgoing.length <= 1) return eds;
    const keepId = outgoing[0].id;
    return eds.filter(e => !(e.source === nodeId && e.sourceHandle === "out" && e.id !== keepId));
  });
}
```

### JavaScript — rehydrate כשגרף נטען מ-server
```javascript
// בתוך map של restored nodes:
schema: (schema?.type === "MyNodeClassName")
  ? {
      ...schema,
      outputs: (n.props?.mode === "single")
        ? [{ name: "out", type: "message", multi: false, label: "out" }]
        : [{ name: "out", type: "message", multi: true,  label: "out" }]
    }
  : schema,
```

---

## 9. helpers זמינים מ-`base_node`

```python
from nodes.base_node import _resource_name, _tf_name, _node_by_id, _node_label

_resource_name(node_dict)
# → שם ה-GCP resource מהפרופ "name" או מה-label עם slug

_tf_name(node_dict)
# → שם בטוח ל-Terraform module (אותיות קטנות, מקפים, ללא רווחים)

_node_by_id(all_nodes, node_id)
# → מחזיר את ה-node dict לפי id (None אם לא נמצא)

_node_label(node_dict)
# → label קריא לאדם לשימוש בלוגים
```

---

## 10. ctx — מה מגיע ל-pulumi_program

```python
ctx = {
  "node": {                # ה-node dict המלא כפי שנשלח מה-UI
    "id": "abc123",
    "type": "MyNodeClassName",
    "label": "My Resource",
    "props": {             # הפרמטרים שהמשתמש הגדיר
      "name": "my-resource",
      "region": "us-central1",
    }
  },
  # ← כל שאר המפתחות נוספו על-ידי resolve_edges:
  "parent_id": "xyz789",   # דוגמה
  "consumer_ids": [...],   # דוגמה
}
```

---

## 11. checklist לפני סיום

```
□ __init__.py מייצא את ה-class
□ class נגזר מ-GCPNode ומעוטר ב-@dataclass
□ params_schema מוגדר (inline או YAML)
□ inputs + outputs עם PortType נכון
□ node_color, icon, category, description מוגדרים
□ resolve_edges מחזיר True לכל edge רלוונטי
□ dag_deps מחזיר dependencies נכונות
□ pulumi_program מחזיר None כשdependency חסר
□ pulumi.export("name", ...) ו-pulumi.export("id", ...) קיימים
□ terraform_instance_prefix מוגדר
□ terraform_call_vars מחזיר dict עם מחרוזות HCL
□ terraform/variables.tf, main.tf, outputs.tf קיימים
□ live_outputs מחזיר dict
□ log_source מחזיר LogSource או None
□ אם יש show_if: patch בJS נוסף (סעיף 7)
□ אם יש dynamic ports: handlePropChange + rehydrate (סעיף 8)
□ כל פרמטר שניתן לפתור מחיבור edge — מוגדר כ-auto-from-edge (סעיף 13)
```

---

## 13. עיקרון ה-Connection-Driven Parameters (חובה לעקוב)

> **כלל היסוד**: כל ערך שניתן להסיק מחיבור edge בין שני צמתים **חייב** להיפתר
> אוטומטית דרך החיבור — ולא לדרוש הקלדה ידנית בלבד.
> ערך ידני נשאר תמיד כ-fallback, אך לא כדרך העיקרית.

### מה זה אומר בפועל

כאשר נוד A מחובר לנוד B ו-A מספק מידע ש-B צריך:
1. `resolve_edges` של B (או A) שומר את `src_id` / `tgt_id` ב-`ctx`
2. `dag_deps` של B מחזיר את `src_id` כדי שA יפרוס קודם
3. `pulumi_program` של B מביא את הערך מ-`deployed_outputs[src_id]`
4. `terraform_call_vars` / `terraform_blocks` של B בונה reference ל-Terraform output של A

### דוגמאות לחיבורים שחייבים לפתור פרמטרים אוטומטית

| חיבור (src → tgt)                | פרמטר שנפתר ב-tgt         | מפתח ב-ctx          | output מ-src          |
|-----------------------------------|---------------------------|---------------------|-----------------------|
| `PubsubTopicNode → Sub`           | `topic_name`              | `topic_id`          | `name`                |
| `Sub(push) → CloudRunNode`        | `push_endpoint`           | `push_target_ids`   | `uri`                 |
| `ServiceAccountNode → CloudRun`   | `service_account_email`   | `service_account_id`| `email`               |
| `ServiceAccountNode → Sub(push)`  | `oidc_sa_email`           | `service_account_id`| `email`               |
| `ServiceAccountNode → IamBinding` | `principal`               | `service_account_id`| `email`               |
| `SubnetworkNode → CloudRun`       | `vpc_network/subnetwork`  | `subnetwork_id`     | `network_path/...`    |
| `CloudTasksQueueNode → CloudRun`  | `CLOUD_TASKS_QUEUE_*` env | `task_queue_ids`    | `queue_name`          |
| `PubsubTopicNode → CloudRun`      | `PUBSUB_TOPIC_*` env      | `publishes_to_topics`| `name`               |

### מה כבר עובד נכון ✅

- **ServiceAccount → CloudRun**: `service_account_id` ב-ctx → `sa_email` מ-deployed_outputs ← ✅
- **Topic → Subscription**: `topic_id` ב-ctx → `topic_name` ← ✅
- **Sub(push) → CloudRun**: `push_target_ids` ב-ctx → `push_endpoint` מ-uri ← ✅
- **ServiceAccount → IamBinding**: `service_account_id` ב-ctx → `principal` ← ✅
- **IamBinding → CloudRun/GCS/etc**: `target_bindings` ב-ctx → resource-level IAM inline ← ✅

### מה לא עבד ותוקן 🔧

- **ServiceAccount → Sub(push)**: נוסף פורט כניסה `oidc_service_account` ל-`PubsubSubscriptionNode`;
  `resolve_edges` של הסאב מטפל כעת ב-`src_type == "ServiceAccountNode"` ושומר `service_account_id`;
  `_pulumi.py` ו-`_terraform.py` כבר קוראים `ctx["service_account_id"]` לפיתרון ה-OIDC email.
- **IamBinding → PubsubSubscription/Topic**: נוספו ל-`_RESOURCE_TYPE_MAP` ול-`_TF_RESOURCE`
  ב-`iam_binding.py`; נוסף טיפול Pulumi ב-`SubscriptionIAMMember` / `TopicIAMMember`.

### תבנית resolve_edges לנוד שמקבל חיבורים מסוגים שונים

```python
def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
    # ── אני ה-TARGET (מישהו מתחבר אלי) ──────────────────────────────────
    if tgt_id == self.node_id:
        if src_type == "ServiceAccountNode":
            ctx[self.node_id]["service_account_id"] = src_id
            return True
        if src_type == "SubnetworkNode":
            ctx[self.node_id]["subnetwork_id"] = src_id
            return True
        if src_type == "SomeOtherNode":
            ctx[self.node_id].setdefault("other_ids", []).append(src_id)
            return True

    # ── אני ה-SOURCE (אני מתחבר למישהו) ─────────────────────────────────
    if src_id == self.node_id:
        ctx[tgt_id]["parent_id"] = self.node_id
        return True

    return False
```

### טיפול ב-Terraform — resource-level vs project-level

**בעיה**: כל resource type ב-GCP דורש Terraform resource שונה לIAM
(למשל `google_cloud_run_v2_service_iam_member` vs `google_storage_bucket_iam_member`).
לא ניתן לטפל בזה דרך module גנרי.

**פתרון**: נודים כמו `IamBindingNode` ו-`ServiceAccountNode` משתמשים ב-`terraform_blocks()`
(inline path) ולא ב-`terraform_call_vars()` (static module path).
`terraform_blocks()` מבצע dispatch לפי `resource_type` ובונה את בלוק HCL הנכון.

**כלל**: כאשר כותבים נוד שמייצר IAM bindings לסוגים שונים של resources —
תמיד ממש את `terraform_blocks()` עם dispatch על `resource_type`,
ואל תסתמך על module גנרי.

---

## 12. דוגמה מינימלית — נוד פשוט מקצה לקצה

```python
# nodes/resource/my_queue/my_queue.py
from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar
import pulumi, pulumi_gcp as gcp
from nodes.base_node import GCPNode, LogSource, Port, _resource_name
from nodes.port_types import PortType
import logging
logger = logging.getLogger(__name__)

@dataclass
class MyQueueNode(GCPNode):
    params_schema: ClassVar = [
        {"key": "name",     "label": "Queue Name", "type": "text",   "default": "", "category": "Basic"},
        {"key": "max_size", "label": "Max Size",   "type": "number", "default": 100, "category": "Basic"},
    ]
    inputs:      ClassVar = []
    outputs:     ClassVar = [Port("messages", PortType.MESSAGE, multi=True)]
    node_color:  ClassVar = "#8b5cf6"
    icon:        ClassVar = "queue"
    category:    ClassVar = "Messaging"
    description: ClassVar = "Simple task queue"

    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool:
        if src_id == self.node_id:
            ctx[tgt_id].setdefault("queue_ids", []).append(self.node_id)
            return True
        return False

    def dag_deps(self, ctx) -> list[str]:
        return []

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props = node_dict.get("props", {})

        def program() -> None:
            q = gcp.cloudtasks.Queue(
                self.node_id,
                name=_resource_name(node_dict),
                location=region,
                project=project,
            )
            pulumi.export("name", q.name)
            pulumi.export("id",   q.id)
        return program

    @property
    def terraform_instance_prefix(self): return "queue"

    def terraform_call_vars(self, ctx, project, region, all_nodes):
        props = ctx.get("node", {}).get("props", {})
        return {
            "name":     f'"{_resource_name(ctx.get("node", {}))}"',
            "location": f'"{region}"',
        }

    def live_outputs(self, pulumi_outputs, project, region):
        return {"queue_name": pulumi_outputs.get("name", "")}

    def log_source(self, pulumi_outputs, project, region):
        name = pulumi_outputs.get("name", "")
        if not name: return None
        return LogSource(
            filter=f'resource.type="cloudtasks.googleapis.com/Queue" AND resource.labels.queue_id="{name}"',
            project=project,
        )
```

```python
# nodes/resource/my_queue/__init__.py
from .my_queue import MyQueueNode
__all__ = ["MyQueueNode"]
```

```hcl
# nodes/resource/my_queue/terraform/variables.tf
variable "name"     { type = string }
variable "location" { type = string; default = "us-central1" }
```

```hcl
# nodes/resource/my_queue/terraform/main.tf
resource "google_cloud_tasks_queue" "main" {
  name     = var.name
  location = var.location
  project  = var.project_id
}
```

```hcl
# nodes/resource/my_queue/terraform/outputs.tf
output "name" { value = google_cloud_tasks_queue.main.name }
output "id"   { value = google_cloud_tasks_queue.main.id }
```