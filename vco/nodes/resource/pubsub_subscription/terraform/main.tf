locals {
  is_push = var.create_push_subscription
}

# ── Pull subscription (created when push_endpoint is empty) ───────────────────
resource "google_pubsub_subscription" "pull" {
  count = local.is_push ? 0 : 1

  name    = var.name
  topic   = var.topic_name
  project = var.project_id

  ack_deadline_seconds          = var.ack_deadline_seconds
  enable_message_ordering       = var.enable_message_ordering
  enable_exactly_once_delivery  = var.enable_exactly_once_delivery

  dynamic "dead_letter_policy" {
    for_each = var.dead_letter_topic != "" ? [1] : []
    content {
      dead_letter_topic = var.dead_letter_topic
    }
  }

  filter = var.filter != "" ? var.filter : null
}

# ── Push subscription (created when push_endpoint is set) ─────────────────────
resource "google_pubsub_subscription" "push" {
  count = local.is_push ? 1 : 0

  name    = var.name
  topic   = var.topic_name
  project = var.project_id

  ack_deadline_seconds = var.ack_deadline_seconds
  filter               = var.filter != "" ? var.filter : null

  push_config {
    push_endpoint = var.push_endpoint

    dynamic "oidc_token" {
      for_each = var.oidc_sa_email != "" ? [1] : []
      content {
        service_account_email = var.oidc_sa_email
      }
    }
  }
}
