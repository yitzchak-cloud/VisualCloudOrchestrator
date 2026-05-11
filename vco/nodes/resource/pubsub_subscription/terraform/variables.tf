# modules/pubsub_subscription/variables.tf

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "name" {
  description = "Subscription name"
  type        = string
}

variable "topic_name" {
  description = "Parent topic name"
  type        = string
}

variable "subscription_type" {
  description = "Subscription type: 'pull' or 'push'"
  type        = string
  default     = "pull"
  validation {
    condition     = contains(["pull", "push"], var.subscription_type)
    error_message = "subscription_type must be 'pull' or 'push'."
  }
}

variable "ack_deadline_seconds" {
  description = "Ack deadline in seconds (10–600)"
  type        = number
  default     = 20
}

variable "filter" {
  description = "Subscription filter expression (empty = no filter)"
  type        = string
  default     = ""
}

# ── pull-only ─────────────────────────────────────────────────────────────────

variable "enable_message_ordering" {
  description = "(pull) Enable message ordering"
  type        = bool
  default     = false
}

variable "enable_exactly_once_delivery" {
  description = "(pull) Enable exactly-once delivery"
  type        = bool
  default     = false
}

# ── push-only ─────────────────────────────────────────────────────────────────

variable "push_endpoint" {
  description = "(push) HTTPS endpoint to deliver messages to"
  type        = string
  default     = ""
}

variable "oidc_sa_email" {
  description = "(push) OIDC service account email for authenticated push (empty = no OIDC)"
  type        = string
  default     = ""
}
