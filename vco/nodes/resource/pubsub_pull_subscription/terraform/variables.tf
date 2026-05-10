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

variable "ack_deadline_seconds" {
  description = "Ack deadline in seconds"
  type        = number
  default     = 20
}

variable "filter" {
  description = "Subscription filter expression"
  type        = string
  default     = ""
}

variable "enable_message_ordering" {
  description = "Enable message ordering"
  type        = bool
  default     = false
}

variable "enable_exactly_once_delivery" {
  description = "Enable exactly-once delivery"
  type        = bool
  default     = false
}
