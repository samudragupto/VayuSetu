# -----------------------------------------------------------------------------
# VayuSetu - Workload Identity Federation for GitHub Actions
#
# GitHub Actions authenticates to Google Cloud with short-lived OIDC tokens. No
# service account keys are created or stored anywhere in the pipeline.
# -----------------------------------------------------------------------------

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "vayusetu-github-pool"
  display_name              = "VayuSetu GitHub Actions"
  description               = "Federated identities for the VayuSetu GitHub repository."
  disabled                  = false

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  description                        = "Trusts tokens issued by GitHub Actions for ${var.github_repository}."

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
  }

  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

locals {
  github_principal_set = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_service_account_iam_member" "deployer_workload_identity" {
  service_account_id = google_service_account.gh_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_principal_set
}

resource "google_service_account_iam_member" "terraform_workload_identity" {
  service_account_id = google_service_account.gh_terraform.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_principal_set
}
