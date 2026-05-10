resource "google_pubsub_topic" "this" {
  name                       = var.name
  project                    = var.project_id
  message_retention_duration = var.retention
}
