"""
pulumi_synth.py
===============
DAG-based deployment using the Pulumi Automation API.

Flow:
  1. resolve_graph()   – parse edges, build dependency context
  2. build_dag()       – topological sort: which node must deploy before which
  3. deploy_dag()      – deploy one node at a time, stream logs per node,
                         pass live Output[str] references between resources
  4. synthesize_only() – preview without deploying

No code generation. Pure Pulumi Automation API inline program per node.

Dependencies:
    pip install pulumi pulumi-gcp
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable

import pulumi
import pulumi_gcp as gcp
from pulumi import automation as auto


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Graph resolver
# ─────────────────────────────────────────────────────────────────────────────

def resolve_graph(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    by_id: dict[str, dict] = {n["id"]: n for n in nodes}
    ctx:   dict[str, dict] = {n["id"]: {"node": n} for n in nodes}

    for edge in edges:
        src      = edge["source"]
        tgt      = edge["target"]
        src_type = by_id.get(src, {}).get("type", "")
        tgt_type = by_id.get(tgt, {}).get("type", "")

        # CloudRun ──► PubsubTopic  (CR publishes to topic)
        if src_type == "CloudRunNode" and tgt_type == "PubsubTopicNode":
            ctx[src].setdefault("publishes_to_topics", []).append(tgt)
            ctx[tgt].setdefault("publisher_cr_ids",    []).append(src)

        # PubsubTopic ──► Subscription
        if src_type == "PubsubTopicNode" and tgt_type in (
            "PubsubPullSubscriptionNode", "PubsubPushSubscriptionNode",
        ):
            ctx[tgt]["topic_id"] = src

        # PullSubscription ──► CloudRun  (CR consumes from sub)
        if src_type == "PubsubPullSubscriptionNode" and tgt_type == "CloudRunNode":
            ctx[src].setdefault("consumer_cr_ids",    []).append(tgt)
            ctx[tgt].setdefault("receives_from_subs", []).append(src)

        # PushSubscription ──► CloudRun  (sub pushes to CR endpoint)
        if src_type == "PubsubPushSubscriptionNode" and tgt_type == "CloudRunNode":
            ctx[src].setdefault("push_target_cr_ids", []).append(tgt)
            ctx[tgt].setdefault("receives_from_subs", []).append(src)

    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# 2.  DAG builder  — topological sort
#
#  Dependency rules (what must exist BEFORE I can deploy X):
#
#    PubsubTopic          → nothing
#    CloudRunNode         → PubsubTopics it publishes to  (needs topic name as env var)
#    PullSubscription     → PubsubTopic it belongs to
#    PushSubscription     → PubsubTopic it belongs to
#                         + CloudRun whose URI it pushes to  (needs live URI)
# ─────────────────────────────────────────────────────────────────────────────

def build_dag(nodes: list[dict], ctx: dict[str, Any]) -> list[str]:
    """
    Returns node IDs in deployment order (topological sort).
    Raises ValueError if a cycle is detected.
    """
    deps: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    for node in nodes:
        nid   = node["id"]
        ntype = node.get("type", "")
        nc    = ctx.get(nid, {})

        if ntype == "CloudRunNode":
            # Must deploy topics first so we can inject their names as env vars
            deps[nid].extend(nc.get("publishes_to_topics", []))

        elif ntype in ("PubsubPullSubscriptionNode", "PubsubPushSubscriptionNode"):
            # Must deploy parent topic first
            if nc.get("topic_id"):
                deps[nid].append(nc["topic_id"])

        if ntype == "PubsubPushSubscriptionNode":
            # Must deploy target Cloud Run first — we need its live URI
            deps[nid].extend(nc.get("push_target_cr_ids", []))

    # Kahn's algorithm
    in_degree: dict[str, int] = defaultdict(int)
    for nid, d_list in deps.items():
        for dep in d_list:
            in_degree[nid] = in_degree.get(nid, 0)   # ensure key exists
        for dep in d_list:
            in_degree[nid]  # just touch; real increment below

    in_degree = defaultdict(int, {n["id"]: 0 for n in nodes})
    for nid, d_list in deps.items():
        for _ in d_list:
            in_degree[nid] += 1

    # Recompute properly: in_degree[X] = number of nodes X depends on
    in_degree = {n["id"]: len(deps[n["id"]]) for n in nodes}

    queue: deque[str] = deque(
        nid for nid in in_degree if in_degree[nid] == 0
    )
    order: list[str] = []
    # reverse dep map: who depends on me?
    rdeps: dict[str, list[str]] = defaultdict(list)
    for nid, d_list in deps.items():
        for dep in d_list:
            rdeps[dep].append(nid)

    while queue:
        nid = queue.popleft()
        order.append(nid)
        for dependent in rdeps[nid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(nodes):
        cycle_nodes = [n["id"] for n in nodes if n["id"] not in order]
        raise ValueError(f"Cycle detected in graph involving: {cycle_nodes}")

    return order


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _node_label(nodes: list[dict], node_id: str) -> str:
    for n in nodes:
        if n["id"] == node_id:
            return n.get("label", node_id)
    return node_id


def _resource_name(node: dict) -> str:
    props = node.get("props", {})
    label = node.get("label", node["id"])
    return props.get("name") or re.sub(r"[^a-z0-9-]", "-", label.lower()).strip("-")


def _make_workspace_opts(work_dir: Path) -> auto.LocalWorkspaceOptions:
    return auto.LocalWorkspaceOptions(
        work_dir=str(work_dir),
        env_vars={
            "PULUMI_BACKEND_URL": os.environ.get(
                "PULUMI_BACKEND_URL",
                f"file://{work_dir / '.pulumi-state'}",
            ),
            "PULUMI_CONFIG_PASSPHRASE": os.environ.get("PULUMI_CONFIG_PASSPHRASE", ""),
            "PULUMI_SKIP_UPDATE_CHECK":  "1",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Single-node inline programs
#     Each returns a () -> None that declares ONLY that one node's resource,
#     using already-deployed Output values passed in via closure.
# ─────────────────────────────────────────────────────────────────────────────

def _program_topic(node: dict, project: str) -> Callable[[], None]:
    def program():
        props = node.get("props", {})
        t = gcp.pubsub.Topic(
            node["id"],
            name=_resource_name(node),
            message_retention_duration=props.get("message_retention_duration", "604800s"),
            project=project,
        )
        pulumi.export("name", t.name)
        pulumi.export("id",   t.id)
    return program


def _program_cloud_run(
    node:            dict,
    project:         str,
    region:          str,
    all_nodes:       list[dict],
    topic_outputs:   dict[str, dict],   # node_id → {"name": Output[str]}
    sub_names:       dict[str, str],    # node_id → plain resource name
) -> Callable[[], None]:
    def program():
        props    = node.get("props", {})
        node_ctx_local = {}
        # Re-resolve just this node's relationships from the stored context
        # (passed in via closure variables topic_outputs / sub_names)
        envs: list[gcp.cloudrunv2.ServiceTemplateContainerEnvArgs] = []

        for topic_id, t_out in topic_outputs.items():
            env_key = "PUBSUB_TOPIC_" + re.sub(
                r"[^A-Z0-9]", "_", _node_label(all_nodes, topic_id).upper()
            )
            envs.append(gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name=env_key,
                value=t_out["name"],   # Output[str] from a previously deployed stack
            ))

        for sub_id, sub_name in sub_names.items():
            env_key = "PUBSUB_SUBSCRIPTION_" + re.sub(
                r"[^A-Z0-9]", "_", _node_label(all_nodes, sub_id).upper()
            )
            envs.append(gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name=env_key,
                value=sub_name,
            ))

        svc = gcp.cloudrunv2.Service(
            node["id"],
            name=_resource_name(node),
            location=region,
            project=project,
            template=gcp.cloudrunv2.ServiceTemplateArgs(
                containers=[gcp.cloudrunv2.ServiceTemplateContainerArgs(
                    image=props.get("image", "gcr.io/cloudrun/hello"),
                    envs=envs or None,
                )],
            ),
        )
        pulumi.export("uri",  svc.uri)
        pulumi.export("name", svc.name)
        pulumi.export("id",   svc.id)
    return program


def _program_pull_subscription(
    node:         dict,
    project:      str,
    topic_name:   Any,   # Output[str]
) -> Callable[[], None]:
    def program():
        props = node.get("props", {})
        sub = gcp.pubsub.Subscription(
            node["id"],
            name=_resource_name(node),
            topic=topic_name,          # Output[str]
            ack_deadline_seconds=props.get("ack_deadline_seconds", 20),
            project=project,
        )
        pulumi.export("name", sub.name)
        pulumi.export("id",   sub.id)
    return program


def _program_push_subscription(
    node:          dict,
    project:       str,
    topic_name:    Any,   # Output[str]
    push_endpoint: Any,   # Output[str] or plain str
) -> Callable[[], None]:
    def program():
        props   = node.get("props", {})
        oidc_sa = props.get("oidc_service_account_email", "")
        sub = gcp.pubsub.Subscription(
            node["id"],
            name=_resource_name(node),
            topic=topic_name,          # Output[str]
            ack_deadline_seconds=props.get("ack_deadline_seconds", 20),
            project=project,
            push_config=gcp.pubsub.SubscriptionPushConfigArgs(
                push_endpoint=push_endpoint,   # Output[str]
                oidc_token=(
                    gcp.pubsub.SubscriptionPushConfigOidcTokenArgs(
                        service_account_email=oidc_sa,
                    ) if oidc_sa else None
                ),
            ),
        )
        pulumi.export("name", sub.name)
        pulumi.export("id",   sub.id)
    return program


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Per-node stack runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_node_stack(
    node_id:    str,
    program:    Callable[[], None],
    stack_name: str,
    work_dir:   Path,
    project:    str,
    region:     str,
    on_output:  Callable[[str], None],
) -> dict:
    """
    Create-or-select a Pulumi stack named  <stack_name>-<node_id>,
    run `up`, and return the stack outputs dict.
    Each node gets its own isolated stack so state is per-resource.
    """
    safe_id    = re.sub(r"[^a-zA-Z0-9_]", "-", node_id)
    full_name  = f"{stack_name}-{safe_id}"
    node_dir   = work_dir / safe_id
    node_dir.mkdir(parents=True, exist_ok=True)

    stack = auto.create_or_select_stack(
        stack_name=full_name,
        project_name="vco-stack",
        program=program,
        opts=_make_workspace_opts(node_dir),
    )
    stack.set_config("gcp:project", auto.ConfigValue(value=project))
    stack.set_config("gcp:region",  auto.ConfigValue(value=region))

    result = stack.up(on_output=on_output, color="never")
    return {k: v.value for k, v in result.outputs.items()}


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Main deploy orchestrator
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_and_deploy(
    nodes:    list[dict],
    edges:    list[dict],
    project:  str,
    region:   str = "us-central1",
    stack:    str = "dev",
    log:      Callable[[str, str, str | None], Any] | None = None,
    work_dir: str | None = None,
) -> dict:
    """
    1. resolve_graph  — build relationship context
    2. build_dag      — topological sort
    3. For each node in order:
         a. build its inline Pulumi program (injecting live outputs from prev nodes)
         b. run stack.up() in a thread (non-blocking)
         c. stream every log line to the WebSocket with node_id tagged
         d. store its outputs (name, uri…) for downstream nodes
    """

    async def _log(msg: str, level: str = "info", node_id: str | None = None) -> None:
        if log:
            await log(msg, level, node_id)  # always 3 args — caller must accept them

    stack_dir = Path(work_dir) if work_dir else Path(
        __import__("tempfile").mkdtemp(prefix="vco_pulumi_")
    )
    stack_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: resolve + sort ───────────────────────────────────────────
    await _log("Phase 1 — Analysing graph dependencies…", "info")
    ctx = resolve_graph(nodes, edges)

    try:
        order = build_dag(nodes, ctx)
    except ValueError as exc:
        await _log(str(exc), "error")
        return {"status": "error", "phase": "dag", "output": str(exc)}

    by_id = {n["id"]: n for n in nodes}
    await _log(
        f"Deployment order ({len(order)} nodes): "
        + " → ".join(_node_label(nodes, nid) for nid in order),
        "info",
    )

    # ── Phase 2: install GCP plugin once ─────────────────────────────────
    await _log("Phase 2 — Installing Pulumi GCP plugin…", "info")
    loop = asyncio.get_event_loop()

    def _install_plugin():
        ws_opts = _make_workspace_opts(stack_dir)
        ws = auto.LocalWorkspace(
            work_dir=str(stack_dir),
            env_vars=ws_opts.env_vars,
        )
        ws.install_plugin("gcp", "v7")

    await loop.run_in_executor(None, _install_plugin)

    # ── Phase 3: deploy node by node ─────────────────────────────────────
    await _log("Phase 3 — Deploying resources…", "info")

    # Stores live outputs keyed by node_id
    deployed_outputs: dict[str, dict] = {}   # node_id → {name, uri, id, …}
    all_node_outputs: dict[str, Any]  = {}   # flat key→value for final result

    total = len(order)

    for index, nid in enumerate(order, start=1):
        node  = by_id[nid]
        ntype = node.get("type", "")
        nc    = ctx.get(nid, {})
        label = _node_label(nodes, nid)

        await _log(f"[{index}/{total}] ▶ {label}  ({ntype})", "info", nid)

        # Notify UI this node is being worked on
        if log:
            # send raw event dict — caller (main.py) can handle it
            await _log("__node_working__", "internal", nid)

        # ── Build the right program ───────────────────────────────────────
        if ntype == "PubsubTopicNode":
            program = _program_topic(node, project)

        elif ntype == "CloudRunNode":
            # Gather topic outputs for topics this CR publishes to
            t_outputs = {
                tid: deployed_outputs[tid]
                for tid in nc.get("publishes_to_topics", [])
                if tid in deployed_outputs
            }
            # Gather subscription names for subs that feed this CR
            s_names = {
                sid: _resource_name(by_id[sid])
                for sid in nc.get("receives_from_subs", [])
                if sid in by_id
            }
            program = _program_cloud_run(
                node, project, region, nodes, t_outputs, s_names
            )

        elif ntype == "PubsubPullSubscriptionNode":
            topic_id  = nc.get("topic_id")
            topic_out = deployed_outputs.get(topic_id, {})
            topic_name = topic_out.get("name", "")
            if not topic_name:
                msg = f"Topic not deployed yet for subscription {label} — skipping"
                await _log(msg, "warn", nid)
                continue
            program = _program_pull_subscription(node, project, topic_name)

        elif ntype == "PubsubPushSubscriptionNode":
            topic_id   = nc.get("topic_id")
            topic_out  = deployed_outputs.get(topic_id, {})
            topic_name = topic_out.get("name", "")
            if not topic_name:
                msg = f"Topic not deployed yet for push subscription {label} — skipping"
                await _log(msg, "warn", nid)
                continue

            push_cr_ids = nc.get("push_target_cr_ids", [])
            if push_cr_ids and push_cr_ids[0] in deployed_outputs:
                push_endpoint = deployed_outputs[push_cr_ids[0]].get("uri", "")
            else:
                push_endpoint = node.get("props", {}).get("push_endpoint", "")

            program = _program_push_subscription(
                node, project, topic_name, push_endpoint
            )

        else:
            await _log(f"Unknown node type {ntype} — skipping", "warn", nid)
            continue

        # ── Run this node's stack in the thread pool ──────────────────────
        def make_on_output(capture_nid: str, capture_label: str):
            def on_output(line: str) -> None:
                level = (
                    "error" if any(w in line.lower() for w in ["error", "failed", "panic"])
                    else "warn"  if "warning" in line.lower()
                    else "ok"    if any(c in line for c in ["+ ", "created", "updated"])
                    else "info"
                )
                asyncio.run_coroutine_threadsafe(
                    _log(f"  {line}", level, capture_nid), loop
                )
            return on_output

        try:
            outputs = await loop.run_in_executor(
                None,
                lambda p=program, n=nid: _run_node_stack(
                    n, p, stack, stack_dir, project, region,
                    make_on_output(n, label),
                ),
            )
            deployed_outputs[nid] = outputs
            all_node_outputs.update({f"{nid}_{k}": v for k, v in outputs.items()})

            await _log(f"[{index}/{total}] ✓ {label} deployed", "ok", nid)
            if log:
                await _log("__node_deployed__", "internal", nid)

        except auto.CommandError as exc:
            await _log(f"[{index}/{total}] ✗ {label} FAILED:\n{exc}", "error", nid)
            if log:
                await _log("__node_failed__", "internal", nid)
            return {
                "status":  "error",
                "phase":   f"node:{nid}",
                "output":  str(exc),
                "outputs": all_node_outputs,
            }

    await _log(f"All {total} resources deployed ✓", "ok")
    return {"status": "ok", "outputs": all_node_outputs}


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Preview (no deploy)
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_only(
    nodes:    list[dict],
    edges:    list[dict],
    project:  str,
    region:   str = "us-central1",
    stack:    str = "dev",
    work_dir: str | None = None,
) -> dict:
    ctx = resolve_graph(nodes, edges)
    try:
        order = build_dag(nodes, ctx)
    except ValueError as exc:
        return {"error": str(exc)}

    slim = {
        k: {key: val for key, val in v.items() if key != "node"}
        for k, v in ctx.items()
    }
    return {
        "deployment_order": [_node_label(nodes, nid) for nid in order],
        "resolved_graph":   slim,
    }