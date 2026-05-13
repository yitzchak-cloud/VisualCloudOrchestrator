variable "name" {
  description = "Topic resource name"
  type        = string
}

variable "region" {
  description = "GCP region (used for resource-scoped IAM bindings)"
  type        = string
}

variable "retention" {
  description = "Message retention duration (e.g. 604800s = 7 days)"
  type        = string
  default     = "604800s"
}

variable "kms_key_name" {
  description = "CMEK key resource name (empty = Google-managed)"
  type        = string
  default     = ""
}
