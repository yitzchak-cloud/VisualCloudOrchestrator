# Visual Cloud Orchestrator (VCO)

GCP infrastructure canvas — draw your cloud, deploy it.

## Structure

```
vco/
├── backend/
│   ├── main.py              # FastAPI server + WebSocket
│   ├── base_node.py         # GCPNode base class
│   ├── nodes.py             # All 7 GCP node types
│   ├── port_types.py        # PortType enum + colors
│   └── requirements.txt
└── frontend/
    └── index.html           # Full React Flow UI (single file)
```

## Run

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
# Any static server works:
python -m http.server 3000
# or: npx serve .
# Then open http://localhost:3000
```

## Usage

1. **Drag** nodes from the left sidebar onto the canvas
2. **Connect** ports — only matching port types can connect (enforced by color)
3. **Configure** — click a node to open the property panel on the right
4. **Deploy** — hit Deploy; watch the log panel and node status indicators
5. **Save** — saves to `state/desired.yaml` (or exports JSON if backend offline)

## Port type rules

| Color | Type | Connects |
|-------|------|----------|
| Purple | ServiceAccount | SA output → SA input |
| Green | Network | VPC output → Cloud Run / SQL input |
| Yellow | Storage | GCS output → Cloud Run writes_to |
| Pink | Secret | SecretManager output → Cloud Run input |
| Blue | Topic | CloudRun/PubSub output → PubSub input |
| Orange | Database | CloudSQL output → (consumer input) |

## Extending with a new node

1. Add a class to `nodes.py` inheriting `GCPNode`
2. Define `inputs`, `outputs`, `node_color`, `icon`, `description` as ClassVars
3. Register it in `NODE_REGISTRY` in `main.py`
4. The UI picks it up automatically on next load

## WebSocket events (backend → UI)

```json
{ "event": "node_status", "node_id": "...", "status": "deployed|error|deploying" }
{ "event": "deploy_started", "total": 5 }
{ "event": "deploy_complete" }
{ "event": "graph_saved", "node_count": 5 }
```
