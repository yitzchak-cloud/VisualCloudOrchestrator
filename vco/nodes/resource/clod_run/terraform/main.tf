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

  template {
    service_account = local.sa_email_resolved

    dynamic "containers" {
      for_each = [1]
      content {
        image = var.image

        dynamic "env" {
          for_each = var.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    dynamic "vpc_access" {
      for_each = local.use_vpc ? [1] : []
      content {
        egress = "PRIVATE_RANGES_ONLY"
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
