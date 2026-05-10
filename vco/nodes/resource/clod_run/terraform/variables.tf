variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "name" {
  description = "Cloud Run service name"
  type        = string
}

variable "image" {
  description = "Container image"
  type        = string
}

variable "location" {
  description = "GCP location (defaults to region)"
  type        = string
  default     = ""
}

variable "ingress" {
  description = "Ingress setting"
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
}

variable "min_instances" {
  description = "Minimum number of instances"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of instances"
  type        = number
  default     = 10
}

variable "sa_email" {
  description = "Service account email (empty = default compute SA)"
  type        = string
  default     = ""
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated public access"
  type        = bool
  default     = false
}

variable "vpc_network" {
  description = "VPC network self-link (empty = no VPC)"
  type        = string
  default     = ""
}

variable "vpc_subnetwork" {
  description = "VPC subnetwork self-link"
  type        = string
  default     = ""
}

variable "env_vars" {
  description = "Environment variables map"
  type        = map(string)
  default     = {}
}
