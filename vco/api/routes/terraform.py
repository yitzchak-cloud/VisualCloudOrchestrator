"""
api/routes/terraform.py
========================
Endpoints for Terraform code generation — fully isolated from Pulumi flow.

POST /api/terraform/preview
    Body: { nodes, edges, namespace, project, region }
    Returns JSON summary (no files written).

POST /api/terraform/generate
    Body: { nodes, edges, namespace, project, region }
    - Generates HCL files
    - Saves them to  state/namespaces/<ns>/terraform/
    - Returns the zip as a binary download

GET  /api/terraform/files?namespace=<ns>
    Returns metadata about the last saved TF workspace for a namespace.

GET  /api/terraform/download?namespace=<ns>
    Re-downloads the last saved TF workspace zip WITHOUT regenerating.

Register in main.py:
    from api.routes import terraform
    app.include_router(terraform.router)
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import os

from terraform_gen import generate_terraform, generate_terraform_summary
from core.state import ns_dir   # reuses existing namespace path helper

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/terraform", tags=["terraform"])


# ── Path helper ───────────────────────────────────────────────────────────────

def _tf_dir(namespace: str) -> Path:
    """
    state/namespaces/<ns>/terraform/
    Created on first access — consistent with logs_dir() / stack_dir().
    """
    d = ns_dir(namespace) / "terraform"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Disk I/O ──────────────────────────────────────────────────────────────────

def _save_tf_files(namespace: str, files: dict[str, str], meta: dict) -> None:
    """
    Write every .tf file to state/namespaces/<ns>/terraform/
    and a manifest.json with generation metadata.
    Subsequent calls overwrite the previous workspace.
    """
    tf_dir = _tf_dir(namespace)
    for filename, content in files.items():
        (tf_dir / filename).write_text(content, encoding="utf-8")

    manifest = {
        **meta,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": list(files.keys()),
    }
    (tf_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "TF workspace saved: namespace=%s  path=%s  files=%d",
        namespace, tf_dir, len(files),
    )


def _load_tf_files(namespace: str) -> tuple[dict[str, str], dict]:
    """
    Load previously saved .tf files.
    Raises FileNotFoundError if no workspace exists yet.
    """
    tf_dir = _tf_dir(namespace)
    manifest_path = tf_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No Terraform workspace found for namespace '{namespace}'"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    for fname in manifest.get("files", []):
        fp = tf_dir / fname
        if fp.exists():
            files[fname] = fp.read_text(encoding="utf-8")

    return files, manifest


def _build_zip(files: dict[str, str], folder: str = "vco-terraform") -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(f"{folder}/{filename}", content.encode("utf-8"))
    buf.seek(0)
    return buf


# ── Request model ─────────────────────────────────────────────────────────────

class TerraformPayload(BaseModel):
    nodes:     list[dict]
    edges:     list[dict]
    namespace: str = Field(default="default")
    project:   str = Field(
        default_factory=lambda: os.getenv("DEFAULT_GCP_PROJECT", "my-gcp-project")
    )
    region: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_GCP_REGION", "us-central1")
    )


# ── Preview ───────────────────────────────────────────────────────────────────

@router.post("/preview")
async def terraform_preview(payload: TerraformPayload):
    """
    Analyse the graph and return a JSON summary of what would be generated.
    Does NOT write any files to disk.
    """
    ns = payload.namespace
    logger.info("TF preview: namespace=%s nodes=%d", ns, len(payload.nodes))

    summary = generate_terraform_summary(nodes=payload.nodes, edges=payload.edges)

    # Include last-saved metadata if a workspace already exists
    saved_at = None
    try:
        _, manifest = _load_tf_files(ns)
        saved_at = manifest.get("generated_at")
    except FileNotFoundError:
        pass

    return {
        "namespace": ns,
        "project":   payload.project,
        "region":    payload.region,
        "saved_at":  saved_at,
        **summary,
    }


# ── Generate + Save + Download ────────────────────────────────────────────────

@router.post("/generate")
async def terraform_generate(payload: TerraformPayload):
    """
    Generate a complete Terraform workspace, persist it to
    state/namespaces/<ns>/terraform/, then stream it as a zip download.

    Subsequent calls for the same namespace overwrite the saved workspace.
    """
    ns = payload.namespace
    node_count = sum(
        1 for n in payload.nodes
        if n.get("type") not in ("vpcGroup", "groupBox", "")
    )
    logger.info(
        "TF generate: namespace=%s nodes=%d project=%s region=%s",
        ns, node_count, payload.project, payload.region,
    )

    # ── Generate HCL ─────────────────────────────────────────────────────────
    files: dict[str, str] = generate_terraform(
        nodes=payload.nodes,
        edges=payload.edges,
        project=payload.project,
        region=payload.region,
    )
    files["README.md"] = _readme(
        project=payload.project,
        region=payload.region,
        namespace=ns,
        node_count=node_count,
    )

    # ── Save to disk under namespace directory ────────────────────────────────
    _save_tf_files(
        namespace=ns,
        files=files,
        meta={
            "namespace":  ns,
            "project":    payload.project,
            "region":     payload.region,
            "node_count": node_count,
        },
    )

    # ── Stream zip to browser ─────────────────────────────────────────────────
    zip_buf = _build_zip(files)
    logger.info("TF zip streamed: %d bytes", zip_buf.getbuffer().nbytes)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="vco-terraform.zip"',
            "X-VCO-Namespace":     ns,
            "X-VCO-Node-Count":    str(node_count),
        },
    )


# ── Metadata endpoint ─────────────────────────────────────────────────────────

@router.get("/files")
async def terraform_files(namespace: str = "default"):
    """
    Return metadata + per-file sizes for the last saved workspace.
    Useful for showing "last generated at …" in the UI without a full download.
    """
    try:
        _, manifest = _load_tf_files(namespace)
    except FileNotFoundError:
        return {
            "namespace":    namespace,
            "generated_at": None,
            "files":        [],
            "tf_dir":       str(_tf_dir(namespace)),
        }

    tf_dir = _tf_dir(namespace)
    file_info = [
        {
            "name":  fname,
            "bytes": (tf_dir / fname).stat().st_size if (tf_dir / fname).exists() else 0,
        }
        for fname in manifest.get("files", [])
    ]
    return {
        "namespace":    namespace,
        "generated_at": manifest.get("generated_at"),
        "project":      manifest.get("project"),
        "region":       manifest.get("region"),
        "node_count":   manifest.get("node_count"),
        "tf_dir":       str(tf_dir),
        "files":        file_info,
    }


# ── Re-download without regeneration ─────────────────────────────────────────

@router.get("/download")
async def terraform_download(namespace: str = "default"):
    """
    Stream the last saved Terraform workspace as a zip.
    Returns 404 if nothing has been generated yet for this namespace.
    Use this to re-download without running the full generator again.
    """
    try:
        files, manifest = _load_tf_files(namespace)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No Terraform workspace found for namespace '{namespace}'. "
                f"POST /api/terraform/generate first."
            ),
        )

    zip_buf  = _build_zip(files)
    ns_clean = namespace.replace("/", "_")

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="vco-terraform-{ns_clean}.zip"',
            "X-VCO-Namespace":     namespace,
            "X-VCO-Generated-At":  manifest.get("generated_at", ""),
        },
    )


# ── README ────────────────────────────────────────────────────────────────────

def _readme(project: str, region: str, namespace: str, node_count: int) -> str:
    tf_path = f"state/namespaces/{namespace}/terraform/"
    return f"""\
# VCO — Generated Terraform Workspace

Generated by **Visual Cloud Orchestrator** from namespace `{namespace}`.

| Field       | Value                     |
|-------------|---------------------------|
| Project     | `{project}`               |
| Region      | `{region}`                |
| Resources   | {node_count}              |
| Server path | `{tf_path}`               |

## Quick Start

```bash
# 1. Install Terraform >= 1.5
# 2. Authenticate with GCP
gcloud auth application-default login

# 3. Edit terraform.tfvars
nano terraform.tfvars

# 4. Run
terraform init
terraform plan
terraform apply
```

## File Layout

| File                | Purpose                               |
|---------------------|---------------------------------------|
| `versions.tf`       | Provider + Terraform version          |
| `variables.tf`      | All input variable declarations       |
| `terraform.tfvars`  | Default values — edit before running  |
| `main.tf`           | All GCP resource blocks               |
| `outputs.tf`        | Exported URLs, names, IDs             |

## Server-Side Storage

The files are also saved on the VCO server at:

    {tf_path}

Re-download the saved workspace without regenerating:

    GET /api/terraform/download?namespace={namespace}

View workspace metadata:

    GET /api/terraform/files?namespace={namespace}

## Recommended Remote State Backend

```hcl
terraform {{
  backend "gcs" {{
    bucket = "your-tfstate-bucket"
    prefix = "vco/{namespace}"
  }}
}}
```
"""