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

variable "push_endpoint" {
  description = "HTTPS push endpoint URL"
  type        = string
}

variable "ack_deadline_seconds" {
  description = "Ack deadline in seconds"
  type        = number
  default     = 20
}

variable "oidc_sa_email" {
  description = "OIDC service account email (empty = no OIDC auth)"
  type        = string
  default     = ""
}

variable "filter" {
  description = "Subscription filter expression"
  type        = string
  default     = ""
}
