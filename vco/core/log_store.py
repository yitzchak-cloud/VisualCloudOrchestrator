"""
core/log_store.py
=================
Persistent log storage + per-node deploy-event extraction.

Files (default ./logs/, override via VCO_LOGS_DIR env var):
  deploy.jsonl       — rolling log, last MAX_LINES lines
  node_events.json   — per-node last-deploy summary (persists across restarts)

Node event structure:
  {
    "node_id":  str,
    "label":    str,
    "status":   "deployed" | "failed" | "no_change" | "skipped",
    "ts":       int (epoch-ms),
    "summary":  str,
    "error":    str | None,
    "outputs":  dict | None,
    "raw":      str,
  }
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGS_DIR   = Path(os.environ.get("VCO_LOGS_DIR", "./logs"))
LOG_FILE   = LOGS_DIR / "deploy.jsonl"
EVENT_FILE = LOGS_DIR / "node_events.json"
MAX_LINES  = 3000

_RE_GCP_ERROR  = re.compile(r"googleapi: Error \d+: (.+?)(?:\. See https?://|$)", re.DOTALL)
_RE_CONSTRAINT = re.compile(r"Constraint (constraints/\S+) violated")
_RE_PULUMI_ERR = re.compile(r"error:\s+sdk[^:]+:\s+(.+?)(?:\n|$)", re.MULTILINE)
_RE_OAUTH2     = re.compile(r'oauth2: "([^"]+)" "([^"]+)"')
_RE_OUTPUTS    = re.compile(r"Outputs:\s*\n((?:[ \t]+\S.*\n?)+)", re.MULTILINE)


def ensure_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def append_log(entry: dict) -> None:
    ensure_dir()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _maybe_rotate()


def read_logs(limit: int = MAX_LINES) -> list[dict]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    out = []
    for raw in lines[-limit:]:
        try:
            out.append(json.loads(raw))
        except Exception:
            pass
    return out


def clear_logs() -> None:
    ensure_dir()
    LOG_FILE.write_text("", encoding="utf-8")


def read_node_events() -> Dict[str, Any]:
    if not EVENT_FILE.exists():
        return {}
    try:
        return json.loads(EVENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def upsert_node_event(node_id: str, event: dict) -> None:
    ensure_dir()
    events = read_node_events()
    events[node_id] = event
    EVENT_FILE.write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_node_event(
    node_id: str,
    label:   str,
    status:  str,
    raw_log: str,
    ts:      Optional[int] = None,
) -> dict:
    """Build a rich structured event from a full Pulumi stdout block."""
    ts = ts or int(time.time() * 1000)

    error_msg: Optional[str] = None
    if status == "failed":
        # Priority 1: oauth2 / auth errors — most actionable
        m_oauth = _RE_OAUTH2.search(raw_log)
        if m_oauth:
            err_code = m_oauth.group(1)
            err_desc = m_oauth.group(2)
            error_msg = f"Auth error: {err_code} — {err_desc}\n→ Run: gcloud auth application-default login"

        # Priority 2: org-policy constraint
        if not error_msg:
            mc = _RE_CONSTRAINT.search(raw_log)
            if mc:
                error_msg = f"Org-policy constraint: {mc.group(1)}"

        # Priority 3: GCP API error
        if not error_msg:
            m = _RE_GCP_ERROR.search(raw_log)
            if m:
                error_msg = m.group(1).strip().rstrip(".")

        # Priority 4: Pulumi SDK error
        if not error_msg:
            m = _RE_PULUMI_ERR.search(raw_log)
            if m:
                error_msg = m.group(1).strip()

    outputs: Optional[dict] = None
    m_out = _RE_OUTPUTS.search(raw_log)
    if m_out:
        outputs = {}
        for line in m_out.group(1).splitlines():
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                outputs[k.strip()] = v.strip().strip('"')

    summary_map = {
        "deployed":  "Deployed successfully",
        "no_change": "No changes — already up to date",
        "skipped":   "Skipped — missing dependency",
        "failed":    error_msg.splitlines()[0] if error_msg else "Deployment failed",
    }

    return {
        "node_id": node_id,
        "label":   label,
        "status":  status,
        "ts":      ts,
        "summary": summary_map.get(status, status),
        "error":   error_msg,
        "outputs": outputs,
        "raw":     raw_log,
    }


def infer_node_event_from_line(
    node_id: str, label: str, msg: str, level: str
) -> Optional[dict]:
    """Lightweight fallback: extract an event from a single terminal log line."""
    ts = int(time.time() * 1000)
    no_change = re.search(r"✓.+— no changes", msg)
    deployed  = re.search(r"✓.+deployed", msg)
    failed    = re.search(r"✗.+FAILED", msg)
    skipped   = re.search(r"⚠.+skipped", msg)

    if no_change:
        return build_node_event(node_id, label, "no_change", msg, ts)
    if deployed:
        return build_node_event(node_id, label, "deployed", msg, ts)
    if failed:
        return build_node_event(node_id, label, "failed", msg, ts)
    if skipped:
        return build_node_event(node_id, label, "skipped", msg, ts)
    return None


def _maybe_rotate() -> None:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LINES * 1.2:
            LOG_FILE.write_text(
                "\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8"
            )
    except Exception:
        pass