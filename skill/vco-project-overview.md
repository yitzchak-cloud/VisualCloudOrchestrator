---
name: vco-project-overview
description: >
  Complete reference for the Visual Cloud Orchestrator (VCO) project.
  Use this skill for ANY task involving this codebase — architecture questions,
  adding features, debugging, understanding how the UI communicates with the server,
  how nodes/resources work, how deployment flows, how namespaces are structured,
  or any question about the project's classes, functions, or logic.
  Trigger whenever the user mentions VCO, Cloud Orchestrator, GCP Visual Designer,
  node types, Pulumi stack, deploy flow, or any file path under vco/.
---

# Visual Cloud Orchestrator — Full Project Reference

## Project Overview

**Visual Cloud Orchestrator (VCO)** is a drag-and-drop GCP infrastructure builder.
The user draws a graph of GCP resources on a canvas; the server converts the graph into Pulumi programs and deploys them to GCP in real time.

- **Frontend**: Single-file React SPA (`index.html`), served statically. No build step — uses Babel standalone + ReactFlow UMD (python -m http.server 3000).
- **Backend**: FastAPI (Python) server at `http://localhost:8000`, run via `uvicorn main:app --reload --port 8000`.
- **Deployment engine**: Pulumi Automation API — each node gets its own isolated Pulumi stack.
- **Alternative export**: Terraform HCL generation (no deploy, download-only).

---

## File / Directory Structure

```
vco/
├── main.py                     # FastAPI entry point, registers all routers
├── pulumi_synth.py             # Backwards-compat shim — re-exports from deploy/
│
├── api/
│   ├── models.py               # Pydantic request/response models
│   └── routes/
│       ├── deploy.py           # POST /api/synth, POST /api/deploy
│       ├── graph.py            # GET /api/state, POST /api/graph, GET /api/actual-state
│       ├── nodes.py            # GET /api/node-types, POST /api/node-schema
│       ├── realtime.py         # GET /api/logs/{node_id} (SSE), WS /ws
│       ├── logs.py             # GET/DELETE /api/deploy-logs/history, node-events
│       ├── namespaces.py       # GET/POST/DELETE /api/namespaces
│       └── terraform.py        # POST /api/terraform/preview|generate, GET /api/terraform/files|download
│
├── core/
│   ├── registry.py             # NODE_REGISTRY — auto-discovers all GCPNode subclasses
│   ├── state.py                # Filesystem path helpers (namespace-scoped)
│   ├── ws_manager.py           # WebSocket connection pool + typed broadcast helpers
│   ├── log_bridge.py           # Translates deploy-engine signals → WS events
│   ├── log_store.py            # Persistent JSONL log storage + node_events.json
│   └── iap_identity.py         # IAP JWT extraction + SA impersonation
│
├── deploy/
│   ├── __init__.py             # Re-exports: build_dag, read_actual_state, resolve_graph,
│   │                           #   synthesize_and_deploy, synthesize_only
│   ├── dag.py                  # build_dag() — topological sort of nodes by dag_deps()
│   ├── graph_resolver.py       # resolve_graph() — walks edges, calls node.resolve_edges()
│   ├── orchestrator.py         # synthesize_and_deploy() — drives the DAG in parallel
│   ├── stack_runner.py         # run_node_stack() — runs one Pulumi stack (blocking, thread pool)
│   ├── state_reader.py         # read_actual_state() — reads live Pulumi state from disk
│   ├── orphan_cleaner.py       # _destroy_node_stack() — destroys stale Pulumi stacks
│   └── pulumi_helpers.py       # get_pulumi_command(), make_workspace_opts()
│
├── nodes/
│   ├── base_node.py            # GCPNode base class, Port, LogSource, TFBlock, TFResult
│   ├── port_types.py           # PortType enum (all edge type constants)
│   └── resource/               # One subdirectory per resource type
│       ├── cloud_run/          # CloudRunNode
│       ├── pubsub_topic/       # PubsubTopicNode
│       ├── pubsub_subscription/ # PubsubSubscriptionNode  ← most up-to-date example
│       │   ├── __init__.py
│       │   ├── pubsub_subscription.py        # Node class (main logic)
│       │   ├── pubsub_subscription_params.yaml # params_schema as YAML
│       │   ├── _pulumi.py                    # make_pulumi_program()
│       │   ├── _terraform.py                 # make_terraform_call_vars(), terraform_instance_prefix()
│       │   └── terraform/                    # Static HCL module files
│       │       ├── main.tf
│       │       ├── variables.tf
│       │       └── outputs.tf
│       ├── service_account/
│       ├── iam_binding/
│       ├── gcs_bucket/
│       ├── cloud_functions/
│       ├── eventarc_trigger/
│       ├── cloud_tasks_queue/
│       ├── workflows/
│       ├── network.py          # VpcNetworkNode, SubnetworkNode
│       └── ...
│
├── terraform_gen/
│   ├── __init__.py
│   └── engine.py               # generate_terraform(), generate_terraform_summary()
│
└── state/
    └── namespaces/
        └── <namespace>/
            ├── desired.yaml        # Saved canvas snapshot
            ├── pulumi_stack/       # Per-node Pulumi stack dirs
            ├── logs/
            │   ├── deploy.jsonl    # Rolling log (max 3000 lines)
            │   └── node_events.json
            └── terraform/          # Generated HCL files + manifest.json
```

---

## API Endpoints

All endpoints are prefixed with the FastAPI router prefix shown below.

### Graph / State
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/state?namespace=default` | Load last saved canvas (nodes + edges) |
| POST | `/api/graph` | Save canvas to `desired.yaml` (body: GraphPayload) |
| GET | `/api/actual-state?namespace=default` | Live Pulumi deployed state |

### Node Types
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/node-types` | Returns all registered node schemas (for sidebar) |
| POST | `/api/node-schema` | Returns a refreshed schema for a node given its current props (dynamic ports) |

### Deploy
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/synth` | Preview deploy plan — no GCP changes (body: SynthPayload) |
| POST | `/api/deploy` | Full Pulumi deploy; progress streamed over WebSocket (body: DeployPayload) |

### Real-time
| Method | Path | Description |
|--------|------|-------------|
| WS | `/ws` | Primary real-time channel; server pushes typed JSON events |
| GET | `/api/logs/{node_id}` | SSE stream of live GCP log lines for a node |

### Logs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/deploy-logs/history?limit=500&namespace=default` | Persisted log history |
| DELETE | `/api/deploy-logs/history?namespace=default` | Clear log file |
| GET | `/api/deploy-logs/node-events?namespace=default` | Per-node last-deploy event map |
| POST | `/api/deploy-logs/node-events/{id}` | Upsert one node event |
| POST | `/api/deploy-logs/append` | Append one log line from frontend |

### Namespaces
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/namespaces` | List all namespaces |
| POST | `/api/namespaces` | Create namespace (body: `{ name }`) |
| DELETE | `/api/namespaces/{name}` | Delete namespace and all its data |

### Terraform
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/terraform/preview` | Analyse graph, return JSON summary (no files written) |
| POST | `/api/terraform/generate` | Generate HCL, save to disk, stream as zip download |
| GET | `/api/terraform/files?namespace=default` | Metadata of last saved TF workspace |
| GET | `/api/terraform/download?namespace=default` | Re-download last saved TF zip |

---

## Pydantic Models (api/models.py)

```python
class GraphPayload:
    nodes: list[dict]    # Canvas node objects
    edges: list[dict]    # Canvas edge objects
    namespace: str = "default"

class DeployPayload:
    nodes: list[dict]
    edges: list[dict]
    namespace: str = "default"
    project: str    # GCP project (env: DEFAULT_GCP_PROJECT)
    region: str     # GCP region (env: DEFAULT_GCP_REGION)
    stack: str = "dev"  # Pulumi stack name

class SynthPayload:
    nodes, edges, namespace, project, region  # same as Deploy, no stack

class NodeSchemaRequest:
    node_type: str
    props: dict = {}
```

---

## WebSocket Event Protocol

All WS messages are JSON. The UI connects on startup and reconnects on close (3s delay).

```jsonc
// Server → Client events:
{ "event": "log",            "msg": "...", "level": "info|ok|warn|err", "node_id": "..." }
{ "event": "node_status",    "node_id": "...", "status": "deploying|deployed|failed|no_change", "action": "create|update|unchanged" }
{ "event": "node_working",   "node_id": "..." }
{ "event": "deploy_started", "create": N, "update": N, "destroy": N, "touched_ids": [...] }
{ "event": "deploy_complete","changed": N, "failed": N }
{ "event": "deploy_outputs", "outputs": { "node_id": { "uri": "...", ... } } }
{ "event": "graph_saved",    "node_count": N }
```

Node statuses displayed on canvas: `idle | deploying | working | deployed | failed | no_change | error`

---

## Node Base Class (nodes/base_node.py)

Every resource node is a `@dataclass` that extends `GCPNode`:

```python
@dataclass
class GCPNode:
    node_id: str
    label:   str

    # ClassVar fields (define on subclass):
    params_schema: ClassVar[list[dict]]   # Field definitions for UI panels
    inputs:        ClassVar[list[Port]]   # Input port definitions
    outputs:       ClassVar[list[Port]]   # Output port definitions
    node_color:    ClassVar[str]          # Hex color
    icon:          ClassVar[str]          # Icon name (maps to icons/<name>/<name>.svg)
    category:      ClassVar[str]          # Sidebar category
    description:   ClassVar[str]          # Tooltip text

    # Methods to implement:
    def resolve_edges(self, src_id, tgt_id, src_type, tgt_type, ctx) -> bool: ...
    def dag_deps(self, ctx) -> list[str]: ...
    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs) -> Callable: ...
    def live_outputs(self, pulumi_outputs, project, region) -> dict: ...
    def log_source(self, pulumi_outputs, project, region) -> LogSource | None: ...

    # Optional — override for dynamic ports:
    def get_outputs(self) -> list[Port]: ...
    def get_inputs(self) -> list[Port]: ...

    # Optional Terraform:
    @property
    def terraform_dir(self) -> Path | None: ...
    @property
    def terraform_instance_prefix(self) -> str: ...
    def terraform_call_vars(self, ctx, project, region, all_nodes) -> dict: ...
```

### Port

```python
@dataclass
class Port:
    name:     str        # Handle ID used in edges
    type:     PortType   # Must match on both ends of an edge
    multi:    bool = True    # Output: allows >1 outgoing edges
    multi_in: bool = False   # Input: allows >1 incoming edges
    required: bool = False   # UI shows warning if unconnected
    color:    str  = "#60a5fa"  # Visual color of the handle
    label:    str  = ""         # Short type badge shown in node body
```

### params_schema Field Definition

Each entry in `params_schema` (list of dicts, can be in a sidecar `.yaml` file):

```yaml
- key: field_name           # prop key in node.data.props
  label: Human Label
  type: text|number|select|checkbox|yaml|code|json
  default: ""
  placeholder: "..."
  options: [a, b, c]        # for type=select
  category: "Basic"         # groups fields in panels
  description: >            # shown as tooltip
    ...
  show_if:                  # conditional visibility
    other_field_key: value
  triggers_refresh: true    # causes POST /api/node-schema when value changes
  auto_from_port: true      # value auto-filled from incoming edge
  cascade_parent: other_key # options loaded from catalog[props[cascade_parent]]
  catalog: { parent_val: [opts] }
```

---

## Port Types (nodes/port_types.py)

```python
class PortType(str, Enum):
    SERVICE_ACCOUNT    = "service_account"
    HTTP_TARGET        = "http"
    STORAGE            = "storage"
    TOPIC              = "topic"
    MESSAGE            = "message"
    NETWORK            = "network"
    TASK_QUEUE         = "task_queue"
    IAM_BINDING        = "iam_binding"
    VISUAL_CONNECTION  = "visual"
    DIRECT_EVENT       = "direct_event"
    # ... (add more as created)
```

Two ports can only connect if their `PortType` values match exactly. The UI enforces this in `onConnect` and shows a toast on mismatch.

---

## Deployment Flow

1. **UI** calls `POST /api/deploy` with all nodes + edges.
2. **deploy.py** broadcasts `deploy_started` via WebSocket, then calls `synthesize_and_deploy()`.
3. **graph_resolver.py** (`resolve_graph`) iterates edges; each node's `resolve_edges()` is called to populate `ctx[node_id]` (DAG context dict).
4. **dag.py** (`build_dag`) topologically sorts nodes using each node's `dag_deps(ctx)` return value.
5. **orchestrator.py** deploys nodes in DAG order (respecting dependencies); independent nodes can run in parallel via `asyncio.get_event_loop().run_in_executor`.
6. **stack_runner.py** (`run_node_stack`) for each node:
   - Creates/selects a Pulumi stack at `state/namespaces/<ns>/pulumi_stack/<safe_node_id>/`
   - Sets GCP project + region config
   - Calls `stack.up()` (blocking, in thread pool)
   - Returns outputs dict
7. **log_bridge.py** converts sentinel strings (`__node_deployed__`, etc.) to WS `node_status` events.
8. After deploy, UI auto-saves graph via `POST /api/graph`.

### Node ctx Dict

During `resolve_graph`, each node gets `ctx[node_id]` initialized with `{"node": <node_dict>}`.
Nodes populate additional keys via `resolve_edges()`, e.g.:
- `ctx[sub_id]["topic_id"] = topic_node_id`
- `ctx[cr_id]["receives_from"] = [sub_id]`
- `ctx[iam_id]["target_bindings"] = [{"node_id": cr_id, "resource_type": "cloud_run_service"}]`

The `pulumi_program(ctx, project, region, all_nodes, deployed_outputs)` receives:
- `ctx[self.node_id]` — everything resolved for this node
- `deployed_outputs` — `{ node_id: { output_key: value } }` of already-deployed nodes

---

## Namespace System

Each namespace is a fully isolated workspace:
```
state/namespaces/<ns>/
    desired.yaml          ← canvas snapshot
    pulumi_stack/         ← per-node Pulumi stack directories
    logs/deploy.jsonl     ← rolling deploy log (max 3000 lines)
    logs/node_events.json ← per-node last-event summary
    terraform/            ← generated HCL + manifest.json
```

- Namespace name: `^[a-zA-Z0-9_-]{1,64}$`
- "default" cannot be deleted
- Switching namespace reloads graph, logs, and node events from server

---

## UI Architecture (index.html)

Single React SPA using ReactFlow. Key React components:

| Component | Role |
|-----------|------|
| `VCOApp` | Root app; owns all state (nodes, edges, logs, namespaces, WebSocket) |
| `GCPNode` | ReactFlow custom node; shows header, ports, status badge, toolbar |
| `GCPEdge` | ReactFlow custom edge; animated dashed line, mid-point delete button |
| `PropertyPanel` | Right panel shown when a node is selected (single-click) |
| `NodeEditModal` | Full modal with all params_schema fields (double-click or toolbar tune icon) |
| `YamlCodeEditor` | CodeMirror 6 modal for yaml/json/code fields |
| `VPCGroupNode` | Container node that holds children (VPC Network group) |
| `LogPanel` | Bottom log drawer (resizable, filterable, searchable, pop-out) |
| `TerraformExportModal` | Generate + download HCL zip |
| `ToastContainer` | Ephemeral status toasts |

### Key UI State

```javascript
// In VCOApp:
const [nodes, setNodes, onNodesChange] = useNodesState([]);  // ReactFlow nodes
const [edges, setEdges, onEdgesChange] = useEdgesState([]);  // ReactFlow edges
const [namespace, setNamespace] = useState("default");
const [nodeTypesData, setNodeTypesData] = useState([]);      // from GET /api/node-types
const [nodeEvents, setNodeEvents] = useState({});            // per-node last deploy event
const [logs, setLogs] = useState([]);                        // deploy log entries
const [isDeploying, setIsDeploying] = useState(false);
const [selectedNode, setSelectedNode] = useState(null);      // right panel
const [editModalNode, setEditModalNode] = useState(null);    // edit modal
```

### Node Data Shape

Each ReactFlow node has:
```javascript
{
  id: "CloudRunNode-1234567890",   // "{NodeType}-{Date.now()}"
  type: "gcpNode",                 // always "gcpNode" for resource nodes
  position: { x, y },
  data: {
    label: "My Service",
    schema: { ...nodeTypeSchema },  // from GET /api/node-types
    status: "idle|deployed|deploying|working|failed|error",
    props: { name: "...", region: "..." },  // user-set params
    accentColor: "#3b82f6",         // optional override color
    collapsed: false,
  }
}
```

### UI → Server Communication

| Action | HTTP Call |
|--------|-----------|
| App startup | `GET /api/node-types` then `GET /api/state?namespace=...` |
| Save (Ctrl+S / menu) | `POST /api/graph` |
| Deploy | `POST /api/deploy` → then WebSocket updates |
| Namespace switch | `GET /api/state?namespace=...` + `GET /api/deploy-logs/...` |
| Param triggers_refresh | `POST /api/node-schema` → refreshes schema/ports live |
| Node live logs button | `GET /api/logs/{node_id}` (SSE EventSource) |
| Terraform export | `POST /api/terraform/generate` → download zip |

### Edge Connection Rules (UI-enforced)

1. `sourcePort.type !== targetPort.type` → blocked (type mismatch toast)
2. `!targetPort.multi_in && already connected` → blocked (single-connection port)
3. `sourcePort.multi === false && already connected` → blocked (single outgoing)
4. On connect with `direct_event` target type → auto-detects provider from source node type and writes `provider` prop to target node

### Dynamic Schema Refresh

When a field has `triggers_refresh: true` (e.g. `subscription_type` in PubsubSubscriptionNode):
1. `handlePropChange` detects the flag
2. Calls `POST /api/node-schema` with current props
3. Server returns a fresh schema (possibly different ports)
4. UI drops any edges that reference now-invalid port names
5. Updates node schema + syncs `selectedNode` + `editModalNode`

---

## Node Registry

`core/registry.py` auto-discovers all `GCPNode` subclasses by walking the `nodes` package via `pkgutil.walk_packages`. The resulting `NODE_REGISTRY: dict[str, type]` maps class name → class.

`GET /api/node-types` serialises each registered node to a JSON schema object used by the UI sidebar and `GCPNode` renderer.

---

## Filesystem Layout (State)

```
state/
└── namespaces/
    └── <ns>/
        ├── desired.yaml          # Saved by POST /api/graph
        ├── pulumi_stack/
        │   └── <safe_node_id>/   # safe_id = re.sub(r"[^a-zA-Z0-9_]", "-", node_id)
        │       ├── Pulumi.yaml
        │       └── .pulumi-state/  # local file backend
        ├── logs/
        │   ├── deploy.jsonl      # JSONL, one entry per line, max 3000 lines
        │   └── node_events.json  # { node_id: { status, summary, error, outputs, raw, ts, label } }
        └── terraform/
            ├── manifest.json
            ├── versions.tf
            ├── variables.tf
            ├── terraform.tfvars
            ├── main.tf
            ├── outputs.tf
            └── modules/
                └── <module_type>/
                    ├── main.tf
                    ├── variables.tf
                    └── outputs.tf
```

---

## Terraform Generation

`terraform_gen/engine.py` (`generate_terraform`):
1. Calls `resolve_graph(nodes, edges, NODE_REGISTRY)` to get ctx
2. For each node, finds its class via `NODE_REGISTRY`
3. Instantiates the class, calls `node.terraform_dir` (path to static HCL)
4. Copies static module files to `modules/<module_type>/`
5. Calls `node.terraform_call_vars(ctx, project, region, all_nodes)` for per-instance variables
6. Builds `module "<prefix>_<tf_name>" { ... }` call block in `main.tf`
7. Returns dict of `{ relative_path: content }`

Module instance naming: `<terraform_instance_prefix>_<tf_name(node)>`, e.g. `cr_my_service`, `ps_my_sub`.

---

## Log Store Format

`deploy.jsonl` — one JSON object per line:
```json
{ "ts": "14:32:01", "level": "ok|info|warn|err", "msg": "...", "node_id": "...|null" }
```

`node_events.json` — dict keyed by node_id:
```json
{
  "CloudRunNode-123": {
    "node_id": "CloudRunNode-123",
    "label": "My Service",
    "status": "deployed|failed|no_change|skipped",
    "ts": 1700000000000,
    "summary": "Deployed successfully",
    "error": null,
    "outputs": { "uri": "https://...", "name": "..." },
    "raw": "full pulumi output text"
  }
}
```

---

## Available Resource Node Types

| Node Class | Category | Description |
|---|---|---|
| `CloudRunNode` | Compute | Cloud Run service |
| `PubsubTopicNode` | Messaging | Pub/Sub topic |
| `PubsubSubscriptionNode` | Messaging | Pub/Sub subscription (pull or push, dynamic ports) |
| `ServiceAccountNode` | IAM | Service account |
| `IamBindingNode` | IAM | IAM role binding (project or resource-level) |
| `GcsBucketNode` | Storage | Cloud Storage bucket |
| `CloudFunctionsNode` | Compute | Cloud Functions (gen2) |
| `EventarcTriggerNode` | Events | Eventarc trigger |
| `CloudTasksQueueNode` | Tasks | Cloud Tasks queue |
| `WorkflowNode` | Orchestration | Cloud Workflows |
| `VpcNetworkNode` | Networking | Shared-VPC network reference |
| `SubnetworkNode` | Networking | VPC subnetwork reference |
| `AuditLogTriggerNode` | Events | Eventarc trigger on Cloud Audit Log |
| `DirectEventTriggerNode` | Events | Direct event trigger |
| `FirestoreNode` | Database | Firestore database |
| `BigQueryNode` | Data | BigQuery dataset/table |
| `CloudSqlNode` | Database | Cloud SQL instance |
| `CloudSchedulerNode` | Scheduling | Cloud Scheduler job |
| `SecretManagerNode` | Security | Secret Manager secret |
| `ArtifactRegistryNode` | Registry | Artifact Registry repository |

UI-only grouping nodes (not deployed):
- `vpcGroup` — VPC group container (visual grouping + network wiring)
- `groupBox` — Visual-only label group

---

## Key Behaviors and Gotchas

- **Server base URL** is hardcoded in `index.html` as `const SERVER_BASE_URL = 'http://localhost:8000'`.
- **GCP icon loading**: tries `icons/<formatted_type>/<formatted_type>.svg` first; falls back to Material Symbol from `ICONS` map.
- **Auto-save after deploy**: `POST /api/graph` is called ~600ms after `deploy_complete` WS event.
- **Node IDs**: format `{NodeType}-{Date.now()}`, e.g. `CloudRunNode-1778657632234`.
- **Edge IDs**: auto-generated by ReactFlow as `reactflow__edge-{source}-{sourceHandle}-{target}-{targetHandle}`.
- **Pulumi stack isolation**: each node is its own Pulumi stack (`state/namespaces/<ns>/pulumi_stack/<safe_id>/`). Stacks share a single local file backend per namespace.
- **Orphan cleanup**: when nodes are removed from the graph and re-deployed, `orphan_cleaner.py` calls `stack.destroy()` + `shutil.rmtree` on stale stack dirs.
- **`handlePropChange(nodeId, key, value, isProp=false)`**: `isProp=false` sets `data[key]` directly (e.g. `label`, `accentColor`); `isProp=true` sets `data.props[key]`.
- **VCOContext**: React context exposing `openNodeLogs`, `openEditModal`, `onDisconnectEdge` to child components.
