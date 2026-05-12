locals {
  # Resolve email: created SA email or provided existing email
  sa_email   = var.create_sa ? google_service_account.this[0].email : var.existing_email
  member_str = "serviceAccount:${local.sa_email}"
}

# ── Service Account ────────────────────────────────────────────────────────────
# Created only when create_sa = true.

resource "google_service_account" "this" {
  count        = var.create_sa ? 1 : 0
  account_id   = var.account_id
  display_name = var.display_name != "" ? var.display_name : var.account_id
  project      = var.project_id
}

# ── Project-level IAM bindings ─────────────────────────────────────────────────
# One google_project_iam_member per role in var.project_roles.

resource "google_project_iam_member" "project_roles" {
  for_each = toset(var.project_roles)
  project  = var.project_id
  role     = each.value
  member   = local.member_str

  # Ensure SA exists before binding when create_sa = true
  depends_on = [google_service_account.this]
}

# ── Resource-level IAM bindings ────────────────────────────────────────────────
# Resource-scoped bindings (cloud_run_service, cloud_function, cloud_tasks_queue)
# are emitted as separate inline TFBlocks by ServiceAccountNode.terraform_blocks()
# because each GCP resource type needs a different Terraform resource type and
# different attribute names. They cannot be templated generically here.
#
# var.resource_bindings is accepted for interface compatibility only.
