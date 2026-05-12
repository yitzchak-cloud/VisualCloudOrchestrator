variable "project_id" {
  description = "GCP project ID"
  type        = string
}

output "name" {
  description = "Topic resource name"
  value       = google_pubsub_topic.topic.name
}

output "id" {
  description = "Topic resource ID"
  value       = google_pubsub_topic.topic.id
}
