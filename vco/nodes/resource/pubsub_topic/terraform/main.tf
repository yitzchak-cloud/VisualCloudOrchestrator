resource "google_pubsub_topic" "topic" {
  name    = var.name
  project = var.project_id

  message_retention_duration = var.retention

  dynamic "message_storage_policy" {
    for_each = []  # reserved for future region restrictions
    content {
      allowed_persistence_regions = []
    }
  }

  kms_key_name = var.kms_key_name != "" ? var.kms_key_name : null
}
