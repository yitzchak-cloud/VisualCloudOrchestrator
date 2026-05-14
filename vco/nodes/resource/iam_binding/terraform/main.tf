# ── Project-level binding ──────────────────────────────────────────────────────

resource "google_project_iam_member" "project_binding" {
  count   = var.project_role != "" ? 1 : 0
  project = var.project_id
  role    = var.project_role
  member  = var.member
}

# ── Cloud Run v2 ───────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service_iam_member" "cloud_run_binding" {
  count    = (var.resource_role != "" && var.cloud_run_service_name != "") ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = var.cloud_run_service_name
  role     = var.resource_role
  member   = var.member
}

# ── GCS Bucket ────────────────────────────────────────────────────────────────

resource "google_storage_bucket_iam_member" "gcs_bucket_binding" {
  count  = (var.resource_role != "" && var.gcs_bucket_name != "") ? 1 : 0
  bucket = var.gcs_bucket_name
  role   = var.resource_role
  member = var.member
}

# ── Cloud Tasks Queue ─────────────────────────────────────────────────────────

resource "google_cloud_tasks_queue_iam_member" "cloud_tasks_binding" {
  count    = (var.resource_role != "" && var.cloud_tasks_queue_name != "") ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = var.cloud_tasks_queue_name
  role     = var.resource_role
  member   = var.member
}

# ── Cloud Function ────────────────────────────────────────────────────────────

resource "google_cloudfunctions_function_iam_member" "cloud_function_binding" {
  count          = (var.resource_role != "" && var.cloud_function_name != "") ? 1 : 0
  project        = var.project_id
  region         = var.region
  cloud_function = var.cloud_function_name
  role           = var.resource_role
  member         = var.member
}

# ── Pub/Sub Subscription ──────────────────────────────────────────────────────

resource "google_pubsub_subscription_iam_member" "pubsub_subscription_binding" {
  count        = (var.resource_role != "" && var.pubsub_subscription_name != "") ? 1 : 0
  project      = var.project_id
  subscription = var.pubsub_subscription_name
  role         = var.resource_role
  member       = var.member
}

# ── Pub/Sub Topic ─────────────────────────────────────────────────────────────

resource "google_pubsub_topic_iam_member" "pubsub_topic_binding" {
  count   = (var.resource_role != "" && var.pubsub_topic_name != "") ? 1 : 0
  project = var.project_id
  topic   = var.pubsub_topic_name
  role    = var.resource_role
  member  = var.member
}

resource "google_artifact_registry_repository_iam_member" "artifact_registry_binding" {
  count   = (var.resource_role != "" && var.artifact_registry_repository_name != "") ? 1 : 0
  project = var.project_id
  location = var.region
  repository = var.artifact_registry_repository_name
  role    = var.resource_role
  member  = var.member
}