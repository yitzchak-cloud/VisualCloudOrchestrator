output "email" {
  description = "Email address of the Service Account"
  value       = local.sa_email
}

output "account_id" {
  description = "Account ID of the Service Account"
  value       = var.create_sa ? google_service_account.this[0].account_id : split("@", var.existing_email)[0]
}

output "id" {
  description = "Full resource ID of the Service Account (empty in reference mode)"
  value       = var.create_sa ? google_service_account.this[0].id : ""
}

output "member" {
  description = "IAM member string ready for use in IAM bindings"
  value       = local.member_str
}
