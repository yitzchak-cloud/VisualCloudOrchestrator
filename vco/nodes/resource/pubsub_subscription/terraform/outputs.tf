locals {
  sub_name = local.is_push ? google_pubsub_subscription.push[0].name : google_pubsub_subscription.pull[0].name
  sub_id   = local.is_push ? google_pubsub_subscription.push[0].id   : google_pubsub_subscription.pull[0].id
}

output "name" {
  description = "Subscription resource name"
  value       = local.sub_name
}

output "id" {
  description = "Subscription resource ID"
  value       = local.sub_id
}
