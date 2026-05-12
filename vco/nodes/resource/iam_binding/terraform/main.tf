# ── Project-level binding ──────────────────────────────────────────────────────
# Created only when project_role is non-empty.

resource "google_project_iam_member" "project_binding" {
  count   = var.project_role != "" ? 1 : 0
  project = var.project_id
  role    = var.project_role
  member  = var.member
}

# ── Resource-level bindings ────────────────────────────────────────────────────
# Resource-level bindings (cloud_run_service, gcs_bucket, cloud_tasks_queue,
# cloud_function) are emitted as individual inline TFBlocks by
# IamBindingNode.terraform_blocks() — they cannot be templated generically
# because each GCP resource type needs a different Terraform resource type and
# different attribute names (name vs bucket vs cloud_function etc.).
#
# This module therefore only handles the project-level binding above.
# The inline blocks path (terraform_blocks) is the authoritative path for
# resource-level IAM; this file is used by the static module path.
