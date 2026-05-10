variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "name" {
  description = "Topic name"
  type        = string
}

variable "retention" {
  description = "Message retention duration"
  type        = string
  default     = "604800s"
}
