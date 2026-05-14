resource "google_artifact_registry_repository" "this" {
  repository_id = var.repository_id
  location      = var.location
  project       = var.project_id
  format        = var.format
  description   = var.description != "" ? var.description : null
}