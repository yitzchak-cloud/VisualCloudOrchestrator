output "member" {
  description = "The IAM member string that was granted the role"
  value       = var.member
}

output "project_role" {
  description = "The project-level role that was granted (empty if skipped)"
  value       = var.project_role
}
