variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "display_name" {
  description = "Display name for the notification channel"
  type        = string
}

variable "channel_type" {
  description = "GCP notification channel type (email, slack, webhook_tokenauth, pagerduty, pubsub)"
  type        = string
  default     = "email"
}

variable "labels" {
  description = "Channel-specific label map (e.g. email_address, channel_name)"
  type        = map(string)
  default     = {}
}

variable "source_type" {
  description = "Source node type (informational — used in alert policy naming)"
  type        = string
  default     = ""
}
