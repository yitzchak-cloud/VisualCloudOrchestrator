"""
terraform_gen/context_builder.py
=================================
Builds the per-node "ctx" dict that generators read.

This mirrors the logic in deploy/graph_resolver.py but is completely
independent of the Pulumi engine.  It walks the edges once and populates
relationship keys (subnetwork_id, service_account_id, topic_id, …) so
generators know what is wired to what.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_tf_context(
    nodes: list[dict],
    edges: list[dict],
) -> dict[str, dict]:
    """
    Build a ctx dict identical in structure to the one produced by
    deploy/graph_resolver.resolve_graph().

    Returns:
        { node_id: { "node": <raw_dict>, ...relationship_keys... } }
    """
    by_id: dict[str, dict] = {n["id"]: n for n in nodes}
    ctx:   dict[str, dict] = {n["id"]: {"node": n} for n in nodes}

    for edge in edges:
        src      = edge.get("source", "")
        tgt      = edge.get("target", "")
        src_type = by_id.get(src, {}).get("type", "")
        tgt_type = by_id.get(tgt, {}).get("type", "")
        s_handle = edge.get("sourceHandle", "")
        t_handle = edge.get("targetHandle", "")

        # ── Service Account ────────────────────────────────────────────────────
        if src_type == "ServiceAccountNode":
            ctx[tgt].setdefault("service_account_id", src)

        # ── VPC Network → Subnetwork ───────────────────────────────────────────
        if src_type == "VpcNetworkNode" and tgt_type == "SubnetworkNode":
            ctx[tgt]["vpc_network_id"] = src

        # ── Subnetwork → Cloud Run / Job ───────────────────────────────────────
        if src_type == "SubnetworkNode" and tgt_type in ("CloudRunNode", "CloudRunJobNode"):
            ctx[tgt]["subnetwork_id"] = src

        # ── Pub/Sub Topic → Subscription ──────────────────────────────────────
        if src_type == "PubsubTopicNode" and tgt_type in (
            "PubsubPullSubscriptionNode",
            "PubsubPushSubscriptionNode",
            "PubsubBigQuerySubscriptionNode",
            "PubsubCloudStorageSubscriptionNode",
        ):
            ctx[tgt]["topic_id"] = src
            ctx[src].setdefault("subscription_ids", []).append(tgt)

        # ── Pub/Sub Topic → Eventarc ───────────────────────────────────────────
        if src_type == "PubsubTopicNode" and tgt_type == "EventarcTriggerNode":
            ctx[tgt]["topic_source_id"] = src

        # ── PubsubPullSub → CloudRun (MESSAGE port) ────────────────────────────
        if src_type in ("PubsubPullSubscriptionNode", "PubsubPushSubscriptionNode") and tgt_type == "CloudRunNode":
            ctx[tgt].setdefault("receives_from_subs", []).append(src)

        # ── Push subscription → Cloud Run target ───────────────────────────────
        if src_type == "PubsubPushSubscriptionNode" and tgt_type == "CloudRunNode":
            ctx[src].setdefault("push_target_ids", []).append(tgt)

        # ── Cloud Run → Pub/Sub Topic (publisher) ──────────────────────────────
        if src_type == "CloudRunNode" and tgt_type == "PubsubTopicNode":
            ctx[src].setdefault("publishes_to_topics", []).append(tgt)

        # ── Cloud Run Job → Pub/Sub Topic ──────────────────────────────────────
        if src_type == "CloudRunJobNode" and tgt_type == "PubsubTopicNode":
            ctx[src].setdefault("publishes_to_topics", []).append(tgt)

        # ── GCS Bucket → Cloud Run (STORAGE port) ─────────────────────────────
        if src_type == "GcsBucketNode" and tgt_type == "CloudRunNode":
            ctx[tgt].setdefault("bucket_ids", []).append(src)

        # ── GCS Bucket → Eventarc (BUCKET port) ───────────────────────────────
        if src_type == "GcsBucketNode" and tgt_type == "EventarcTriggerNode":
            ctx[tgt]["bucket_source_id"] = src

        # ── Cloud Run → GCS Bucket (writes_to port) ────────────────────────────
        if src_type == "CloudRunNode" and tgt_type == "GcsBucketNode":
            ctx[tgt].setdefault("writer_ids", []).append(src)

        # ── Workflow → GCS Bucket ──────────────────────────────────────────────
        if src_type == "WorkflowNode" and tgt_type == "GcsBucketNode":
            ctx[tgt].setdefault("writer_ids", []).append(src)

        # ── Cloud Tasks Queue → Cloud Run (TASK_QUEUE port) ────────────────────
        if src_type == "CloudTasksQueueNode" and tgt_type == "CloudRunNode":
            ctx[tgt].setdefault("task_queue_ids", []).append(src)

        # ── Cloud Scheduler → Cloud Run (HTTP_TARGET) ──────────────────────────
        if src_type == "CloudSchedulerNode" and tgt_type == "CloudRunNode":
            ctx[src].setdefault("target_run_ids", []).append(tgt)

        # ── Cloud Scheduler → Cloud Run Job (RUN_JOB) ──────────────────────────
        if src_type == "CloudSchedulerNode" and tgt_type == "CloudRunJobNode":
            ctx[src].setdefault("target_job_ids", []).append(tgt)

        # ── Cloud Scheduler → Pub/Sub Topic (TOPIC) ────────────────────────────
        if src_type == "CloudSchedulerNode" and tgt_type == "PubsubTopicNode":
            ctx[src].setdefault("target_topic_ids", []).append(tgt)

        # ── Eventarc Trigger → Cloud Run (EVENT port) ──────────────────────────
        if src_type == "EventarcTriggerNode" and tgt_type == "CloudRunNode":
            ctx[src].setdefault("target_run_ids", []).append(tgt)

        # ── Workflow → Cloud Run (HTTP_TARGET) ─────────────────────────────────
        if src_type == "WorkflowNode" and tgt_type == "CloudRunNode":
            ctx[src].setdefault("target_run_ids", []).append(tgt)

    logger.debug("TF context built for %d nodes", len(nodes))
    return ctx
