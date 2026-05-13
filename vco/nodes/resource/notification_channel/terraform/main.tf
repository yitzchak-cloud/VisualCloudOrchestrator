resource "google_monitoring_notification_channel" "this" {
  display_name = var.display_name
  type         = var.channel_type
  labels       = var.labels
  project      = var.project_id
}
