variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "name" {
  description = "Subscription resource name"
  type        = string
}

variable "topic_name" {
  description = "Full topic name this subscription attaches to"
  type        = string
}

variable "ack_deadline_seconds" {
  description = "Ack deadline in seconds (10–600)"
  type        = number
  default     = 20
}

variable "filter" {
  description = "CEL filter expression (empty = no filter)"
  type        = string
  default     = ""
}

# ── Pull-only ──────────────────────────────────────────────────────────────

variable "enable_message_ordering" {
  description = "Enable ordered delivery (pull only)"
  type        = bool
  default     = false
}

variable "enable_exactly_once_delivery" {
  description = "Enable exactly-once delivery (pull only)"
  type        = bool
  default     = false
}

variable "dead_letter_topic" {
  description = "Dead-letter topic resource name (pull only, empty = disabled)"
  type        = string
  default     = ""
}

# ── Push-only ──────────────────────────────────────────────────────────────

variable "push_endpoint" {
  description = "HTTPS push endpoint URL (push only)"
  type        = string
  default     = ""
}

variable "oidc_sa_email" {
  description = "OIDC service account email for push auth (push only)"
  type        = string
  default     = ""
}
