# ── Core ──────────────────────────────────────────────────────────────────────

variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "member" {
  type        = string
  description = "Full IAM member string, e.g. serviceAccount:sa@project.iam.gserviceaccount.com"
}

# ── Project-level binding ──────────────────────────────────────────────────────

variable "project_role" {
  type    = string
  default = ""
}

# ── Resource-level binding ─────────────────────────────────────────────────────

variable "resource_role" {
  type    = string
  default = ""
}

# ── Cloud Run ──────────────────────────────────────────────────────────────────

variable "cloud_run_service_name" {
  type    = string
  default = ""
  description = "Name of the Cloud Run v2 service. Set to enable resource-level binding."
}

# ── GCS Bucket ────────────────────────────────────────────────────────────────

variable "gcs_bucket_name" {
  type    = string
  default = ""
  description = "Name of the GCS bucket. Set to enable resource-level binding."
}

# ── Cloud Tasks Queue ─────────────────────────────────────────────────────────

variable "cloud_tasks_queue_name" {
  type    = string
  default = ""
  description = "Name of the Cloud Tasks queue. Set to enable resource-level binding."
}

# ── Cloud Function ────────────────────────────────────────────────────────────

variable "cloud_function_name" {
  type    = string
  default = ""
  description = "Name of the Cloud Function. Set to enable resource-level binding."
}

# ── Pub/Sub Subscription ──────────────────────────────────────────────────────

variable "pubsub_subscription_name" {
  type    = string
  default = ""
  description = "Name of the Pub/Sub subscription. Set to enable resource-level binding."
}

# ── Pub/Sub Topic ─────────────────────────────────────────────────────────────

variable "pubsub_topic_name" {
  type    = string
  default = ""
  description = "Name of the Pub/Sub topic. Set to enable resource-level binding."
}

# ── Artifact Registry Repository ─────────────────────────────────────────────
variable "artifact_registry_repository_name" {
  type    = string
  default = ""
  description = "Name of the Artifact Registry repository. Set to enable resource-level binding."
}