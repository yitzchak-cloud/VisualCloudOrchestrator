output "name" {
  description = "Display name of the notification channel"
  value       = google_monitoring_notification_channel.this.display_name
}

output "channel_name" {
  description = "Full GCP resource name of the notification channel"
  value       = google_monitoring_notification_channel.this.name
}

output "channel_type" {
  description = "Channel type"
  value       = google_monitoring_notification_channel.this.type
}
