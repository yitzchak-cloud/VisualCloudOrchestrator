"""
core/log_store.py
=================
Persistent log storage + per-node deploy-event extraction.

All file paths are now **namespace-scoped**.  Every public function that
touches the filesystem accepts an optional *namespace* keyword argument
(default ``"default"``).  Internal helpers that were already called with
explicit paths continue to work unchanged.

Files per namespace  (under logs_dir(namespace)/):
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
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import namespace-aware path helpers
from core.state import logs_dir as _logs_dir

MAX_LINES = 3000

_RE_GCP_ERROR  = re.compile(r"googleapi: Error \d+: (.+?)(?:\. See https?://|$)", re.DOTALL)
_RE_CONSTRAINT = re.compile(r"Constraint (constraints/\S+) violated")
_RE_PULUMI_ERR = re.compile(r"error:\s+sdk[^:]+:\s+(.+?)(?:\n|$)", re.MULTILINE)
_RE_OAUTH2     = re.compile(r'oauth2: "([^"]+)" "([^"]+)"')
_RE_OUTPUTS    = re.compile(r"Outputs:\s*\n((?:[ \t]+\S.*\n?)+)", re.MULTILINE)


# ── Path helpers ──────────────────────────────────────────────────────────────

def _log_file(namespace: str = "default") -> Path:
    return _logs_dir(namespace) / "deploy.jsonl"


def _event_file(namespace: str = "default") -> Path:
    return _logs_dir(namespace) / "node_events.json"


# ── Log CRUD ──────────────────────────────────────────────────────────────────

def append_log(entry: dict, namespace: str = "default") -> None:
    lf = _log_file(namespace)
    with open(lf, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _maybe_rotate(namespace)


def read_logs(limit: int = MAX_LINES, namespace: str = "default") -> list[dict]:
    lf = _log_file(namespace)
    if not lf.exists():
        return []
    lines = lf.read_text(encoding="utf-8").splitlines()
    out = []
    for raw in lines[-limit:]:
        try:
            out.append(json.loads(raw))
        except Exception:
            pass
    return out


def clear_logs(namespace: str = "default") -> None:
    _log_file(namespace).write_text("", encoding="utf-8")


# ── Node events CRUD ──────────────────────────────────────────────────────────

def read_node_events(namespace: str = "default") -> Dict[str, Any]:
    ef = _event_file(namespace)
    if not ef.exists():
        return {}
    try:
        return json.loads(ef.read_text(encoding="utf-8"))
    except Exception:
        return {}


def upsert_node_event(node_id: str, event: dict, namespace: str = "default") -> None:
    events = read_node_events(namespace)
    events[node_id] = event
    _event_file(namespace).write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Event builder ─────────────────────────────────────────────────────────────

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
        m_oauth = _RE_OAUTH2.search(raw_log)
        if m_oauth:
            error_msg = (
                f"Auth error: {m_oauth.group(1)} — {m_oauth.group(2)}\n"
                "→ Run: gcloud auth application-default login"
            )
        if not error_msg:
            mc = _RE_CONSTRAINT.search(raw_log)
            if mc:
                error_msg = f"Org-policy constraint: {mc.group(1)}"
        if not error_msg:
            m = _RE_GCP_ERROR.search(raw_log)
            if m:
                error_msg = m.group(1).strip().rstrip(".")
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


# ── Rotation ──────────────────────────────────────────────────────────────────

def _maybe_rotate(namespace: str = "default") -> None:
    try:
        lf = _log_file(namespace)
        lines = lf.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LINES * 1.2:
            lf.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass