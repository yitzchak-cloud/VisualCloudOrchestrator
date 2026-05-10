output "uri" {
  description = "Service URI"
  value       = google_cloud_run_v2_service.this.uri
}

output "name" {
  description = "Service name"
  value       = google_cloud_run_v2_service.this.name
}
