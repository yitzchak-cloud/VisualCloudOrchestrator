output "name" {
  description = "Topic name"
  value       = google_pubsub_topic.this.name
}

output "id" {
  description = "Topic ID"
  value       = google_pubsub_topic.this.id
}
