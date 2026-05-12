variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region (used for resource-scoped IAM bindings)"
  type        = string
}

variable "create_sa" {
  description = "When true, create the Service Account. When false, reference existing_email."
  type        = bool
  default     = true
}

variable "account_id" {
  description = "Account ID for the SA (generates <account_id>@<project>.iam.gserviceaccount.com)"
  type        = string
  default     = ""
}

variable "display_name" {
  description = "Human-readable display name shown in GCP console"
  type        = string
  default     = ""
}

variable "existing_email" {
  description = "Email of an existing SA (used when create_sa = false)"
  type        = string
  default     = ""
}

variable "project_roles" {
  description = "List of IAM roles to grant to the SA at project level"
  type        = list(string)
  default     = []
}

variable "resource_bindings" {
  description = <<-EOT
    JSON-encoded list of resource-scoped IAM bindings.
    Each item: { resource_type, resource_ref, role }
    Note: resource-level bindings are emitted as inline TFBlocks by
    terraform_blocks() and do not pass through this variable at runtime.
    This variable is informational for the module interface.
  EOT
  type        = string
  default     = "[]"
}
