output "uri" {
  description = "HTTPS URI of the Cloud Run service"
  value       = google_cloud_run_v2_service.this.uri
}

output "name" {
  description = "Cloud Run service name"
  value       = google_cloud_run_v2_service.this.name
}

output "id" {
  description = "Full resource ID of the Cloud Run service"
  value       = google_cloud_run_v2_service.this.id
}

output "service_url" {
  description = "Alias for uri — used by live_outputs in the VCO node"
  value       = google_cloud_run_v2_service.this.uri
}
