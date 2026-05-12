variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region (used for resource-level bindings that require location)"
  type        = string
}

variable "member" {
  description = "IAM member string (e.g. serviceAccount:..., user:..., allUsers)"
  type        = string
}

variable "project_role" {
  description = "IAM role to grant at project level. Empty string = skip."
  type        = string
  default     = ""
}

variable "resource_role" {
  description = "IAM role to grant on each target resource. Empty string = skip."
  type        = string
  default     = ""
}

# Note: resource-level bindings are expressed as separate inline TFBlocks by
# terraform_blocks() rather than passing resource names into this module.
# These variables are retained for the static terraform_call_vars() interface
# used by the module-based code path.

variable "target_resource_names" {
  description = "List of Terraform resource name identifiers for target resources (informational)"
  type        = list(string)
  default     = []
}

variable "target_resource_types" {
  description = "List of resource type strings matching target_resource_names"
  type        = list(string)
  default     = []
}
