resource "google_pubsub_subscription" "this" {
  name                         = var.name
  topic                        = var.topic_name
  project                      = var.project_id
  ack_deadline_seconds         = var.ack_deadline_seconds
  filter                       = var.filter != "" ? var.filter : null
  enable_message_ordering      = var.enable_message_ordering
  enable_exactly_once_delivery = var.enable_exactly_once_delivery
}
