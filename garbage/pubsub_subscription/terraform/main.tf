# modules/pubsub_subscription/main.tf
# ─────────────────────────────────────────────────────────────────────────────
# Unified Pub/Sub subscription module — supports both pull and push.
# subscription_type = "pull" → standard pull subscription (no push_config)
# subscription_type = "push" → push delivery to push_endpoint
# ─────────────────────────────────────────────────────────────────────────────

locals {
  is_push  = var.subscription_type == "push"
  use_oidc = local.is_push && var.oidc_sa_email != ""
}

resource "google_pubsub_subscription" "this" {
  name                         = var.name
  topic                        = var.topic_name
  project                      = var.project_id
  ack_deadline_seconds         = var.ack_deadline_seconds
  filter                       = var.filter != "" ? var.filter : null

  # pull-only settings — ignored by GCP when push_config is present
  enable_message_ordering      = local.is_push ? false : var.enable_message_ordering
  enable_exactly_once_delivery = local.is_push ? false : var.enable_exactly_once_delivery

  dynamic "push_config" {
    for_each = local.is_push ? [1] : []
    content {
      push_endpoint = var.push_endpoint

      dynamic "oidc_token" {
        for_each = local.use_oidc ? [1] : []
        content {
          service_account_email = var.oidc_sa_email
        }
      }
    }
  }
}
