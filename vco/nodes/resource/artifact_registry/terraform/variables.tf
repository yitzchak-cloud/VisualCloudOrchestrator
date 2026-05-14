variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "location" {
  description = "GCP region or location"
  type        = string
}

variable "repository_id" {
  description = "The repository ID"
  type        = string
}

variable "format" {
  description = "The format of the repository (e.g., DOCKER, MAVEN, NPM)"
  type        = string
  default     = "DOCKER"
}

variable "description" {
  description = "Repository description"
  type        = string
  default     = ""
}