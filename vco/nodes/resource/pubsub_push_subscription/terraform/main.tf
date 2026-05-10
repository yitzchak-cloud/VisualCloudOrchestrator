locals {
  use_oidc = var.oidc_sa_email != ""
}

resource "google_pubsub_subscription" "this" {
  name                 = var.name
  topic                = var.topic_name
  project              = var.project_id
  ack_deadline_seconds = var.ack_deadline_seconds
  filter               = var.filter != "" ? var.filter : null

  push_config {
    push_endpoint = var.push_endpoint

    dynamic "oidc_token" {
      for_each = local.use_oidc ? [1] : []
      content {
        service_account_email = var.oidc_sa_email
      }
    }
  }
}
