# -----------------------------------------------------------------------------
# VayuSetu - Service accounts and least-privilege IAM
#
# Every runtime component has its own service account. Project-level roles are
# granted only where the target resource does not support resource-level IAM
# (for example BigQuery job creation) or where the resource is created later by
# the deployment pipeline (Cloud Functions).
# -----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Service accounts
# ---------------------------------------------------------------------------

resource "google_service_account" "api_gateway" {
  project      = var.project_id
  account_id   = "vayusetu-api-gateway"
  display_name = "VayuSetu WhatsApp API gateway (Cloud Run)"
  description  = "Receives Twilio webhooks, stores images and logs report metadata."
}

resource "google_service_account" "fn_vision" {
  project      = var.project_id
  account_id   = "vayusetu-fn-vision"
  display_name = "VayuSetu Gemini vision function"
  description  = "Extracts structured pollution indicators from citizen images."
}

resource "google_service_account" "fn_gee" {
  project      = var.project_id
  account_id   = "vayusetu-fn-gee"
  display_name = "VayuSetu Earth Engine function"
  description  = "Fetches Sentinel-5P and MODIS metrics for each report."
}

resource "google_service_account" "fn_alerts" {
  project      = var.project_id
  account_id   = "vayusetu-fn-alerts"
  display_name = "VayuSetu alerting function"
  description  = "Sends multilingual voice and WhatsApp alerts to authorities."
}

resource "google_service_account" "fn_batch" {
  project      = var.project_id
  account_id   = "vayusetu-fn-batch"
  display_name = "VayuSetu batch prediction function"
  description  = "Aggregates observations and calls the prediction service."
}

resource "google_service_account" "prediction" {
  project      = var.project_id
  account_id   = "vayusetu-prediction"
  display_name = "VayuSetu XGBoost prediction service (Cloud Run)"
  description  = "Serves 12-hour AQI forecasts."
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "vayusetu-scheduler"
  display_name = "VayuSetu Cloud Scheduler invoker"
  description  = "Identity used by Cloud Scheduler to invoke the batch prediction function."
}

resource "google_service_account" "gh_deployer" {
  project      = var.project_id
  account_id   = "vayusetu-gh-deployer"
  display_name = "VayuSetu GitHub Actions application deployer"
  description  = "Deploys Cloud Run revisions, Cloud Functions and Firebase Hosting."
}

resource "google_service_account" "gh_terraform" {
  project      = var.project_id
  account_id   = "vayusetu-gh-terraform"
  display_name = "VayuSetu GitHub Actions Terraform runner"
  description  = "Applies this Terraform configuration from GitHub Actions."
}

locals {
  runtime_service_accounts = {
    api_gateway = google_service_account.api_gateway
    fn_vision   = google_service_account.fn_vision
    fn_gee      = google_service_account.fn_gee
    fn_alerts   = google_service_account.fn_alerts
    fn_batch    = google_service_account.fn_batch
    prediction  = google_service_account.prediction
  }

  firestore_users = {
    api_gateway = google_service_account.api_gateway.email
    fn_vision   = google_service_account.fn_vision.email
    fn_gee      = google_service_account.fn_gee.email
    fn_alerts   = google_service_account.fn_alerts.email
    fn_batch    = google_service_account.fn_batch.email
  }

  bigquery_writers = {
    fn_vision = google_service_account.fn_vision.email
    fn_gee    = google_service_account.fn_gee.email
    fn_alerts = google_service_account.fn_alerts.email
    fn_batch  = google_service_account.fn_batch.email
  }

  event_receivers = {
    fn_vision = google_service_account.fn_vision.email
    fn_gee    = google_service_account.fn_gee.email
    fn_alerts = google_service_account.fn_alerts.email
  }

  # Secret -> service accounts permitted to read it.
  secret_readers = {
    api_gateway_twilio_sid   = { secret = "twilio-account-sid", member = google_service_account.api_gateway.email }
    api_gateway_twilio_token = { secret = "twilio-auth-token", member = google_service_account.api_gateway.email }
    api_gateway_twilio_from  = { secret = "twilio-whatsapp-from", member = google_service_account.api_gateway.email }
    api_gateway_phone_hash   = { secret = "phone-hash-secret", member = google_service_account.api_gateway.email }
    fn_vision_gemini         = { secret = "google-ai-studio-api-key", member = google_service_account.fn_vision.email }
    fn_vision_twilio_sid     = { secret = "twilio-account-sid", member = google_service_account.fn_vision.email }
    fn_vision_twilio_token   = { secret = "twilio-auth-token", member = google_service_account.fn_vision.email }
    fn_vision_twilio_from    = { secret = "twilio-whatsapp-from", member = google_service_account.fn_vision.email }
    fn_alerts_twilio_sid     = { secret = "twilio-account-sid", member = google_service_account.fn_alerts.email }
    fn_alerts_twilio_token   = { secret = "twilio-auth-token", member = google_service_account.fn_alerts.email }
    fn_alerts_twilio_from    = { secret = "twilio-whatsapp-from", member = google_service_account.fn_alerts.email }
    fn_alerts_voice_from     = { secret = "twilio-voice-from", member = google_service_account.fn_alerts.email }
  }

  deployer_project_roles = [
    "roles/run.admin",
    "roles/cloudfunctions.developer",
    "roles/eventarc.developer",
    "roles/artifactregistry.writer",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/firebasehosting.admin",
    "roles/firebaserules.admin",
    "roles/firebase.viewer",
    "roles/logging.viewer",
    "roles/cloudbuild.builds.viewer",
  ]

  terraform_project_roles = [
    "roles/editor",
    "roles/resourcemanager.projectIamAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
    "roles/run.admin",
    "roles/datastore.owner",
    "roles/bigquery.admin",
    "roles/artifactregistry.admin",
    "roles/cloudscheduler.admin",
  ]
}

# ---------------------------------------------------------------------------
# Firestore
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "firestore_users" {
  for_each = local.firestore_users

  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${each.value}"
}

# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset_iam_member" "writers" {
  for_each = local.bigquery_writers

  project    = var.project_id
  dataset_id = google_bigquery_dataset.vayusetu.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "bigquery_job_users" {
  for_each = local.bigquery_writers

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${each.value}"
}

# ---------------------------------------------------------------------------
# Cloud Storage
# ---------------------------------------------------------------------------

resource "google_storage_bucket_iam_member" "gateway_images_writer" {
  bucket = google_storage_bucket.citizen_images.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.api_gateway.email}"
}

resource "google_storage_bucket_iam_member" "vision_images_reader" {
  bucket = google_storage_bucket.citizen_images.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.fn_vision.email}"
}

resource "google_storage_bucket_iam_member" "alerts_audio_admin" {
  bucket = google_storage_bucket.alert_audio.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.fn_alerts.email}"
}

resource "google_storage_bucket_iam_member" "prediction_model_reader" {
  bucket = google_storage_bucket.ml_artifacts.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.prediction.email}"
}

resource "google_storage_bucket_iam_member" "deployer_model_writer" {
  bucket = google_storage_bucket.ml_artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.gh_deployer.email}"
}

# Signed URL generation without exported keys: the service account signs blobs
# through the IAM Credentials API on its own behalf.
resource "google_service_account_iam_member" "gateway_self_token_creator" {
  service_account_id = google_service_account.api_gateway.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.api_gateway.email}"
}

resource "google_service_account_iam_member" "alerts_self_token_creator" {
  service_account_id = google_service_account.fn_alerts.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.fn_alerts.email}"
}

# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret_iam_member" "api_gateway" {
  for_each = { for k, v in local.secret_readers : k => v if v.member == google_service_account.api_gateway.email }

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.member}"
}

resource "google_secret_manager_secret_iam_member" "functions" {
  for_each = { for k, v in local.secret_readers : k => v if v.member != google_service_account.api_gateway.email }

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.member}"
}

# ---------------------------------------------------------------------------
# Eventarc and Pub/Sub plumbing for event-driven functions
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "event_receivers" {
  for_each = local.event_receivers

  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "eventarc_service_agent" {
  project = var.project_id
  role    = "roles/eventarc.serviceAgent"
  member  = "serviceAccount:${google_project_service_identity.eventarc.email}"
}

# Required for authenticated Pub/Sub push subscriptions in projects created
# before April 2021; harmless otherwise.
resource "google_project_iam_member" "pubsub_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:service-${local.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"

  depends_on = [google_project_service_identity.pubsub]
}

# ---------------------------------------------------------------------------
# Earth Engine, Translation
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "gee_viewer" {
  project = var.project_id
  role    = "roles/earthengine.viewer"
  member  = "serviceAccount:${google_service_account.fn_gee.email}"
}

resource "google_project_iam_member" "gee_service_usage" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.fn_gee.email}"
}

resource "google_project_iam_member" "alerts_translate_user" {
  project = var.project_id
  role    = "roles/cloudtranslate.user"
  member  = "serviceAccount:${google_service_account.fn_alerts.email}"
}

# ---------------------------------------------------------------------------
# Cloud Scheduler invoker
# ---------------------------------------------------------------------------

# The batch function is created by the deployment pipeline after Terraform
# runs, so the invoker grant is made at project level for this single-purpose
# identity.
resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_project_iam_member" "scheduler_functions_invoker" {
  project = var.project_id
  role    = "roles/cloudfunctions.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# ---------------------------------------------------------------------------
# GitHub Actions deployer
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset(local.deployer_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gh_deployer.email}"
}

# Deploying a Cloud Run revision or a Cloud Function that runs as a given
# service account requires actAs on that account.
resource "google_service_account_iam_member" "deployer_act_as_runtime" {
  for_each = local.runtime_service_accounts

  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.gh_deployer.email}"
}

# ---------------------------------------------------------------------------
# GitHub Actions Terraform runner
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "terraform_roles" {
  for_each = toset(local.terraform_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gh_terraform.email}"
}
