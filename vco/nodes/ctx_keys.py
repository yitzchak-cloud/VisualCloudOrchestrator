"""
nodes/ctx_keys.py
=================
מפתחות קבועים ל-ctx שמשותפים בין כמה נודים.

שימוש
-----
    from nodes.ctx_keys import K

    # ב-resolve_edges:
    ctx[self.node_id][K.SERVICE_ACCOUNT] = src_id

    # ב-terraform_call_vars:
    sa_id = ctx.get(K.SERVICE_ACCOUNT, "")

TypedDict לנוד ספציפי
---------------------
כל נוד מגדיר TypedDict משלו לשדות הייחודיים לו:

    from typing import TypedDict
    from nodes.ctx_keys import K

    class MyNodeCtx(TypedDict, total=False):
        topic_id:        str        # K.TOPIC_ID
        push_target_ids: list[str]  # ייחודי לנוד הזה

    # ב-resolve_edges:
    nctx: MyNodeCtx = ctx[self.node_id]
    nctx[K.TOPIC_ID] = src_id

כלל: total=False — כל שדה אופציונלי, אין שינוי בלוגיקת setdefault/get.
"""


class K:
    """מפתחות ctx משותפים. השתמש תמיד בקבועים אלה — לא במחרוזות ישירות."""

    # ── זהויות (identity) ──────────────────────────────────────────────────────
    SERVICE_ACCOUNT   = "service_account_id"    # ServiceAccountNode → כל נוד
    SUBNETWORK_ID     = "subnetwork_id"          # SubnetworkNode → CloudRun וכו'

    # ── Pub/Sub ────────────────────────────────────────────────────────────────
    TOPIC_ID          = "topic_id"               # PubsubTopicNode → Subscription / CloudRun
    PUBLISHER_IDS     = "publisher_ids"          # CloudRun → PubsubTopicNode (מי מפרסם)
    PUSH_TARGET_IDS   = "push_target_ids"        # Sub(push) → CloudRun
    CONSUMER_IDS      = "consumer_ids"           # Sub(pull) → consumers
    RECEIVES_FROM     = "receives_from_subs"     # CloudRun ← Sub (נשמר על היעד)
    PUBLISHES_TO      = "publishes_to_topics"    # CloudRun → Topic (env injection)

    # ── Storage ────────────────────────────────────────────────────────────────
    BUCKET_IDS        = "bucket_ids"             # GcsBucketNode → CloudRun
    FIRESTORE_IDS     = "firestore_ids"          # FirestoreNode → CloudRun

    # ── Tasks / Queues ─────────────────────────────────────────────────────────
    TASK_QUEUE_IDS    = "task_queue_ids"         # CloudTasksQueueNode → CloudRun

    # ── IAM ────────────────────────────────────────────────────────────────────
    IAM_BINDINGS      = "target_bindings"        # IamBindingNode → resource

    # ── Visual / misc ──────────────────────────────────────────────────────────
    VISUAL_API_IDS    = "visual_api_ids"         # VisualApiNode → CloudRun

    # ── Generic ────────────────────────────────────────────────────────────────
    PARENT_ID         = "parent_id"              # generic parent ref