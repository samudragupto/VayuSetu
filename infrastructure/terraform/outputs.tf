# -----------------------------------------------------------------------------
# VayuSetu - Outputs consumed by the CI/CD pipelines and local tooling
# -----------------------------------------------------------------------------

output "project_id" {
  description = "Google Cloud project ID."
  value       = var.project_id
}

output "project_number" {
  description = "Google Cloud project number."
  value       = local.project_number
}

output "region" {
  description = "Primary deployment region."
  value       = var.region
}

output "citizen_images_bucket" {
  description = "Cloud Storage bucket that receives citizen images and triggers the Gemini vision function."
  value       = google_storage_bucket.citizen_images.name
}

output "alert_audio_bucket" {
  description = "Cloud Storage bucket that stores synthesised voice alerts."
  value       = google_storage_bucket.alert_audio.name
}

output "ml_artifacts_bucket" {
  description = "Cloud Storage bucket that stores trained XGBoost model artifacts."
  value       = google_storage_bucket.ml_artifacts.name
}

output "firestore_database" {
  description = "Firestore database name."
  value       = google_firestore_database.default.name
}

output "bigquery_dataset" {
  description = "BigQuery dataset ID."
  value       = google_bigquery_dataset.vayusetu.dataset_id
}

output "bigquery_tables" {
  description = "Fully qualified BigQuery table identifiers."
  value = {
    citizen_reports    = "${var.project_id}.${google_bigquery_dataset.vayusetu.dataset_id}.${google_bigquery_table.citizen_reports.table_id}"
    satellite_metrics  = "${var.project_id}.${google_bigquery_dataset.vayusetu.dataset_id}.${google_bigquery_table.satellite_metrics.table_id}"
    predicted_hotspots = "${var.project_id}.${google_bigquery_dataset.vayusetu.dataset_id}.${google_bigquery_table.predicted_hotspots.table_id}"
    alert_log          = "${var.project_id}.${google_bigquery_dataset.vayusetu.dataset_id}.${google_bigquery_table.alert_log.table_id}"
    fused_observations = "${var.project_id}.${google_bigquery_dataset.vayusetu.dataset_id}.${google_bigquery_table.fused_observations.table_id}"
  }
}

output "artifact_registry_repository" {
  description = "Docker repository path for container images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "api_gateway_url" {
  description = "Public URL of the WhatsApp API gateway. Configure this URL (plus /webhooks/twilio/whatsapp) in the Twilio console."
  value       = google_cloud_run_v2_service.api_gateway.uri
}

output "prediction_service_url" {
  description = "Private URL of the XGBoost prediction service."
  value       = google_cloud_run_v2_service.prediction_service.uri
}

output "batch_predict_function_url" {
  description = "Deterministic URL of the batch prediction function invoked by Cloud Scheduler."
  value       = local.batch_predict_url
}

output "cloud_function_names" {
  description = "Names used by the deployment pipeline for each Cloud Function."
  value       = local.function_names
}

output "service_account_emails" {
  description = "Runtime and pipeline service account emails."
  value = {
    api_gateway       = google_service_account.api_gateway.email
    fn_vision         = google_service_account.fn_vision.email
    fn_gee            = google_service_account.fn_gee.email
    fn_alerts         = google_service_account.fn_alerts.email
    fn_batch          = google_service_account.fn_batch.email
    prediction        = google_service_account.prediction.email
    scheduler         = google_service_account.scheduler.email
    github_deployer   = google_service_account.gh_deployer.email
    github_terraform  = google_service_account.gh_terraform.email
  }
}

output "workload_identity_provider" {
  description = "Full resource name of the GitHub OIDC provider. Store it in the GCP_WORKLOAD_IDENTITY_PROVIDER repository variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "secret_ids" {
  description = "Secret Manager secret IDs."
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.secret_id }
}

output "scheduler_job" {
  description = "Cloud Scheduler job that triggers batch prediction."
  value       = google_cloud_scheduler_job.batch_predict.name
}

output "gee_project" {
  description = "Project registered with Google Earth Engine."
  value       = local.gee_project
}

output "github_repository_variables" {
  description = "Values to store as GitHub Actions repository variables."
  value = {
    GCP_PROJECT_ID                 = var.project_id
    GCP_REGION                     = var.region
    GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOYER_SERVICE_ACCOUNT   = google_service_account.gh_deployer.email
    GCP_TERRAFORM_SERVICE_ACCOUNT  = google_service_account.gh_terraform.email
    ARTIFACT_REGISTRY              = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
    CITIZEN_IMAGES_BUCKET          = google_storage_bucket.citizen_images.name
    ALERT_AUDIO_BUCKET             = google_storage_bucket.alert_audio.name
    ML_ARTIFACTS_BUCKET            = google_storage_bucket.ml_artifacts.name
    PREDICTION_SERVICE_URL         = google_cloud_run_v2_service.prediction_service.uri
    ADMIN_DOMAIN                   = var.admin_domain
    GEMINI_MODEL_CANDIDATES        = var.gemini_model_candidates
    ALERT_AQI_THRESHOLD            = tostring(var.alert_aqi_threshold)
    HOTSPOT_GEOHASH_PRECISION      = tostring(var.hotspot_geohash_precision)
    GEE_PROJECT                    = local.gee_project
  }
}
