locals {
  sa_email_resolved = var.sa_email != "" ? var.sa_email : null
  location_resolved = var.location != "" ? var.location : var.region
  use_vpc           = var.vpc_network != "" && var.vpc_subnetwork != ""
}

resource "google_cloud_run_v2_service" "this" {
  name                = var.name
  location            = local.location_resolved
  project             = var.project_id
  deletion_protection = false
  ingress             = var.ingress

  labels      = length(var.labels)      > 0 ? var.labels      : null
  annotations = length(var.annotations) > 0 ? var.annotations : null

  template {
    service_account                   = local.sa_email_resolved
    execution_environment             = var.execution_environment
    max_instance_request_concurrency  = var.concurrency
    timeout                           = "${var.timeout_seconds}s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      ports {
        container_port = var.port
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        startup_cpu_boost = var.startup_cpu_boost
      }

      dynamic "env" {
        for_each = var.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
    }

    dynamic "vpc_access" {
      for_each = local.use_vpc ? [1] : []
      content {
        egress = var.vpc_egress
        network_interfaces {
          network    = var.vpc_network
          subnetwork = var.vpc_subnetwork
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = local.location_resolved
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
