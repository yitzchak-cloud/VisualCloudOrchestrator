# modules/pubsub_subscription/outputs.tf

output "name" {
  description = "Subscription name"
  value       = google_pubsub_subscription.this.name
}

output "id" {
  description = "Subscription ID"
  value       = google_pubsub_subscription.this.id
}
