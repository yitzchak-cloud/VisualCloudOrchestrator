variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region (used as fallback when location is empty)"
  type        = string
}

variable "name" {
  description = "Cloud Run service name"
  type        = string
}

variable "image" {
  description = "Container image URI"
  type        = string
}

variable "location" {
  description = "GCP location (defaults to var.region when empty)"
  type        = string
  default     = ""
}

# ── Container ─────────────────────────────────────────────────────────────────

variable "port" {
  description = "Container port the service listens on"
  type        = number
  default     = 8080
}

variable "cpu" {
  description = "vCPU allocation per instance (e.g. '1', '2', '0.5')"
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory limit per instance (e.g. '512Mi', '1Gi')"
  type        = string
  default     = "512Mi"
}

variable "concurrency" {
  description = "Max concurrent requests per container instance"
  type        = number
  default     = 80
}

variable "timeout_seconds" {
  description = "Max request duration in seconds (1–3600)"
  type        = number
  default     = 300
}

variable "execution_environment" {
  description = "Execution environment generation"
  type        = string
  default     = "EXECUTION_ENVIRONMENT_GEN2"
  validation {
    condition     = contains(["EXECUTION_ENVIRONMENT_GEN1", "EXECUTION_ENVIRONMENT_GEN2"], var.execution_environment)
    error_message = "execution_environment must be EXECUTION_ENVIRONMENT_GEN1 or EXECUTION_ENVIRONMENT_GEN2."
  }
}

variable "startup_cpu_boost" {
  description = "Allocate extra CPU during container startup to reduce cold-start latency"
  type        = bool
  default     = false
}

# ── Scaling ───────────────────────────────────────────────────────────────────

variable "min_instances" {
  description = "Minimum number of instances to keep warm"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of instances"
  type        = number
  default     = 10
}

# ── Access ────────────────────────────────────────────────────────────────────

variable "ingress" {
  description = "Ingress traffic source setting"
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  validation {
    condition = contains([
      "INGRESS_TRAFFIC_ALL",
      "INGRESS_TRAFFIC_INTERNAL_ONLY",
      "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
    ], var.ingress)
    error_message = "ingress must be one of INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_ONLY, INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER."
  }
}

variable "allow_unauthenticated" {
  description = "Grant allUsers roles/run.invoker (public access)"
  type        = bool
  default     = false
}

# ── Networking ────────────────────────────────────────────────────────────────

variable "vpc_egress" {
  description = "VPC egress setting (PRIVATE_RANGES_ONLY or ALL_TRAFFIC)"
  type        = string
  default     = "PRIVATE_RANGES_ONLY"
}

variable "vpc_network" {
  description = "VPC network self-link (empty = no VPC egress)"
  type        = string
  default     = ""
}

variable "vpc_subnetwork" {
  description = "VPC subnetwork self-link"
  type        = string
  default     = ""
}

# ── Identity ──────────────────────────────────────────────────────────────────

variable "sa_email" {
  description = "Service account email (empty = default compute SA)"
  type        = string
  default     = ""
}

# ── Env vars & metadata ───────────────────────────────────────────────────────

variable "env_vars" {
  description = "Environment variables injected into the container"
  type        = map(string)
  default     = {}
}

variable "labels" {
  description = "GCP labels applied to the service resource"
  type        = map(string)
  default     = {}
}

variable "annotations" {
  description = "GCP annotations applied to the service resource"
  type        = map(string)
  default     = {}
}
