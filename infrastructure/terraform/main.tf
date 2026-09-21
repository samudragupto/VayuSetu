# -----------------------------------------------------------------------------
# VayuSetu - Core infrastructure
#
# This file provisions every managed resource that the application depends on:
# project APIs, Cloud Storage, Firestore, BigQuery, Secret Manager, Artifact
# Registry, the two Cloud Run services and the Cloud Scheduler job that drives
# batch prediction. Identity and access management lives in iam.tf and the
# GitHub Actions federation lives in wif.tf.
#
# Cost posture: every resource below is sized to stay inside the Google Cloud
# Always Free tier at hackathon and pilot volumes (see README, section "Cost").
# -----------------------------------------------------------------------------

data "google_project" "current" {
  project_id = var.project_id
}

data "google_storage_project_service_account" "gcs_agent" {
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

locals {
  project_number = data.google_project.current.number
  gee_project    = var.gee_project != "" ? var.gee_project : var.project_id

  common_labels = {
    application = "vayusetu"
    environment = var.environment
    managed-by  = "terraform"
  }

  required_apis = [
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "run.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "eventarc.googleapis.com",
    "pubsub.googleapis.com",
    "firestore.googleapis.com",
    "firebase.googleapis.com",
    "firebaserules.googleapis.com",
    "firebasehosting.googleapis.com",
    "identitytoolkit.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "translate.googleapis.com",
    "texttospeech.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "earthengine.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]

  citizen_images_bucket = "${var.project_id}-vayusetu-citizen-images"
  alert_audio_bucket    = "${var.project_id}-vayusetu-alert-audio"
  ml_artifacts_bucket   = "${var.project_id}-vayusetu-ml-artifacts"

  bigquery_dataset_id = "vayusetu"

  function_names = {
    vision = "process-citizen-image"
    gee    = "fetch-gee-metrics"
    alerts = "send-authority-alerts"
    batch  = "batch-predict"
  }

  # Cloud Functions (2nd gen) expose a deterministic URL in this form. The
  # scheduler job is created before the function itself exists, which is why
  # the URL is computed rather than read from a resource.
  batch_predict_url = "https://${var.region}-${var.project_id}.cloudfunctions.net/${local.function_names.batch}"

  secret_values = {
    "twilio-account-sid"       = var.twilio_account_sid
    "twilio-auth-token"        = var.twilio_auth_token
    "twilio-whatsapp-from"     = var.twilio_whatsapp_from
    "twilio-voice-from"        = var.twilio_voice_from
    "google-ai-studio-api-key" = var.google_ai_studio_api_key
    "phone-hash-secret"        = var.phone_hash_secret != "" ? var.phone_hash_secret : random_password.phone_hash_secret.result
  }
}

# ---------------------------------------------------------------------------
# Project APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Service identities that must exist before Eventarc triggers can be created
# by the deployment pipeline.
resource "google_project_service_identity" "eventarc" {
  provider = google-beta
  project  = var.project_id
  service  = "eventarc.googleapis.com"

  depends_on = [google_project_service.apis]
}

resource "google_project_service_identity" "pubsub" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"

  depends_on = [google_project_service.apis]
}

resource "google_project_service_identity" "cloudfunctions" {
  provider = google-beta
  project  = var.project_id
  service  = "cloudfunctions.googleapis.com"

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Random material
# ---------------------------------------------------------------------------

resource "random_password" "phone_hash_secret" {
  length  = 48
  special = false
}

# ---------------------------------------------------------------------------
# Cloud Storage
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "citizen_images" {
  name          = local.citizen_images_bucket
  project       = var.project_id
  location      = var.region
  storage_class = "STANDARD"
  labels        = local.common_labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !var.enable_deletion_protection

  versioning {
    enabled = false
  }

  # Move older imagery to a cheaper class, then delete it. Citizen images are
  # only needed until Gemini has extracted the structured signal.
  lifecycle_rule {
    condition {
      age = var.image_nearline_after_days
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = var.image_retention_days
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 1
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "alert_audio" {
  name          = local.alert_audio_bucket
  project       = var.project_id
  location      = var.region
  storage_class = "STANDARD"
  labels        = local.common_labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  # Synthesised voice alerts are served through short-lived signed URLs and are
  # not needed after the call has been placed.
  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "ml_artifacts" {
  name          = local.ml_artifacts_bucket
  project       = var.project_id
  location      = var.region
  storage_class = "STANDARD"
  labels        = local.common_labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !var.enable_deletion_protection

  versioning {
    enabled = true
  }

  # Keep the three most recent model versions so a rollback is always possible
  # without accumulating storage cost.
  lifecycle_rule {
    condition {
      num_newer_versions = 3
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# Cloud Storage publishes object events through Pub/Sub. The storage service
# agent must be allowed to publish before an Eventarc trigger can be created.
resource "google_project_iam_member" "gcs_agent_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_agent.email_address}"
}

# ---------------------------------------------------------------------------
# Firestore (Native mode)
# ---------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  concurrency_mode                  = "OPTIMISTIC"
  app_engine_integration_mode       = "DISABLED"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_DISABLED"
  delete_protection_state           = var.enable_deletion_protection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"
  deletion_policy                   = var.enable_deletion_protection ? "ABANDON" : "DELETE"

  depends_on = [google_project_service.apis]
}

# Composite indexes required by the API gateway, the batch job, the alerting
# function and the dashboard. firestore.indexes.json at the repository root
# mirrors this list for the local emulator.
resource "google_firestore_index" "reports_by_status" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "citizen_reports"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "createdAt"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "reports_by_status_analyzed_at" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "citizen_reports"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "analyzedAt"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "reports_by_phone" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "citizen_reports"

  fields {
    field_path = "phoneHash"
    order      = "ASCENDING"
  }
  fields {
    field_path = "createdAt"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "hotspots_by_cell" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "predicted_hotspots"

  fields {
    field_path = "geohash"
    order      = "ASCENDING"
  }
  fields {
    field_path = "generatedAt"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "authorities_by_coverage" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "authorities"

  fields {
    field_path   = "coverageGeohashes"
    array_config = "CONTAINS"
  }
  fields {
    field_path = "active"
    order      = "ASCENDING"
  }
}

# Dashboard and gateway stats: hotspots filtered by alert status within a window.
resource "google_firestore_index" "hotspots_by_alert_status" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "predicted_hotspots"

  fields {
    field_path = "alertStatus"
    order      = "ASCENDING"
  }
  fields {
    field_path = "generatedAt"
    order      = "DESCENDING"
  }
}

# Alert log queries by hotspot for the dashboard detail view.
resource "google_firestore_index" "alert_log_by_hotspot" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "alert_log"

  fields {
    field_path = "hotspotId"
    order      = "ASCENDING"
  }
  fields {
    field_path = "sentAt"
    order      = "DESCENDING"
  }
}

# Access control document consumed by the Firestore security rules and the
# dashboard. Additional administrator e-mail addresses can be appended to
# adminEmails outside of Terraform without affecting this resource.
resource "google_firestore_document" "access_config" {
  project     = var.project_id
  database    = google_firestore_database.default.name
  collection  = "config"
  document_id = "access"

  fields = jsonencode({
    adminDomains = {
      arrayValue = {
        values = [for domain in split(",", var.admin_domain) : { stringValue = trimspace(domain) }]
      }
    }
    adminEmails = {
      arrayValue = { values = [] }
    }
    updatedBy = { stringValue = "terraform" }
  })

  lifecycle {
    ignore_changes = [fields]
  }
}

# Webhook idempotency records expire automatically after seven days.
resource "google_firestore_field" "webhook_events_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "webhook_events"
  field      = "expiresAt"

  ttl_config {}

  # Disable single-field indexing for this collection's TTL field.
  index_config {}
}

# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------

resource "google_bigquery_dataset" "vayusetu" {
  project       = var.project_id
  dataset_id    = local.bigquery_dataset_id
  friendly_name = "VayuSetu air quality warehouse"
  description   = "Fused citizen-science, satellite and forecast data for hyper-local air quality monitoring."
  location      = var.bigquery_location
  labels        = local.common_labels

  delete_contents_on_destroy = !var.enable_deletion_protection

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "citizen_reports" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.vayusetu.dataset_id
  table_id            = "citizen_reports"
  description         = "Structured Gemini vision output for every citizen image."
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels
  schema              = file("${path.module}/schemas/citizen_reports.json")

  time_partitioning {
    type  = "DAY"
    field = "received_at"
  }

  clustering = ["geohash", "city"]
}

resource "google_bigquery_table" "satellite_metrics" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.vayusetu.dataset_id
  table_id            = "satellite_metrics"
  description         = "Sentinel-5P and MODIS metrics fetched from Google Earth Engine for each report."
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels
  schema              = file("${path.module}/schemas/satellite_metrics.json")

  time_partitioning {
    type  = "DAY"
    field = "observed_at"
  }

  clustering = ["geohash"]
}

resource "google_bigquery_table" "predicted_hotspots" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.vayusetu.dataset_id
  table_id            = "predicted_hotspots"
  description         = "12-hour AQI forecasts generated by the XGBoost prediction service."
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels
  schema              = file("${path.module}/schemas/predicted_hotspots.json")

  time_partitioning {
    type  = "DAY"
    field = "generated_at"
  }

  clustering = ["geohash"]
}

resource "google_bigquery_table" "alert_log" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.vayusetu.dataset_id
  table_id            = "alert_log"
  description         = "Audit trail of multilingual voice and WhatsApp alerts sent to authorities."
  deletion_protection = var.enable_deletion_protection
  labels              = local.common_labels
  schema              = file("${path.module}/schemas/alert_log.json")

  time_partitioning {
    type  = "DAY"
    field = "sent_at"
  }

  clustering = ["geohash", "authority_id"]
}

resource "google_bigquery_table" "fused_observations" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.vayusetu.dataset_id
  table_id            = "fused_observations"
  description         = "Deduplicated join of citizen vision metrics and satellite metrics, consumed by the batch prediction job and the training pipeline."
  deletion_protection = false
  labels              = local.common_labels

  view {
    query = templatefile("${path.module}/sql/fused_observations.sql", {
      project = var.project_id
      dataset = google_bigquery_dataset.vayusetu.dataset_id
    })
    use_legacy_sql = false
  }

  depends_on = [
    google_bigquery_table.citizen_reports,
    google_bigquery_table.satellite_metrics,
  ]
}

# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "secrets" {
  for_each = local.secret_values

  project   = var.project_id
  secret_id = "vayusetu-${each.key}"
  labels    = local.common_labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "secrets" {
  for_each = local.secret_values

  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = each.value
}

# ---------------------------------------------------------------------------
# Artifact Registry
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "docker" {
  project       = var.project_id
  location      = var.region
  repository_id = "vayusetu"
  description   = "Container images for the VayuSetu Cloud Run services."
  format        = "DOCKER"
  labels        = local.common_labels

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-recent-images"
    action = "KEEP"

    most_recent_versions {
      keep_count = 3
    }
  }

  cleanup_policies {
    id     = "delete-stale-images"
    action = "DELETE"

    condition {
      older_than = "2592000s"
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Cloud Run - WhatsApp API gateway (Node.js 20)
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api_gateway" {
  project             = var.project_id
  name                = "vayusetu-api-gateway"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.common_labels

  template {
    service_account                  = google_service_account.api_gateway.email
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = var.api_gateway_max_instances
    }

    containers {
      image = var.placeholder_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "NODE_ENV"
        value = "production"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.citizen_images.name
      }
      env {
        name  = "ADMIN_DOMAIN"
        value = var.admin_domain
      }
      env {
        name  = "HOTSPOT_GEOHASH_PRECISION"
        value = tostring(var.hotspot_geohash_precision)
      }
      env {
        name  = "TWILIO_VALIDATE_SIGNATURE"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "info"
      }
      env {
        name = "TWILIO_ACCOUNT_SID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["twilio-account-sid"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TWILIO_AUTH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["twilio-auth-token"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TWILIO_WHATSAPP_FROM"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["twilio-whatsapp-from"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "PHONE_HASH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["phone-hash-secret"].secret_id
            version = "latest"
          }
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # The container image is owned by the GitHub Actions deployment pipeline.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].labels,
      template[0].annotations,
      template[0].revision,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.secrets,
    google_secret_manager_secret_iam_member.api_gateway,
  ]
}

# Twilio must be able to reach the webhook without Google credentials. Request
# authenticity is enforced by the X-Twilio-Signature validation middleware.
resource "google_cloud_run_v2_service_iam_member" "api_gateway_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api_gateway.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Cloud Run - XGBoost prediction service (Python 3.10 / FastAPI)
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "prediction_service" {
  project             = var.project_id
  name                = "vayusetu-prediction-service"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.common_labels

  template {
    service_account                  = google_service_account.prediction.email
    timeout                          = "120s"
    max_instance_request_concurrency = 16

    scaling {
      min_instance_count = 0
      max_instance_count = var.prediction_max_instances
    }

    containers {
      image = var.placeholder_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "MODEL_PATH"
        value = "/app/model/model.joblib"
      }
      env {
        name  = "MODEL_GCS_URI"
        value = "gs://${google_storage_bucket.ml_artifacts.name}/models/model.joblib"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].labels,
      template[0].annotations,
      template[0].revision,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.apis]
}

# Only the batch prediction function may call the model.
resource "google_cloud_run_v2_service_iam_member" "prediction_invoker_batch" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.prediction_service.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.fn_batch.email}"
}

# ---------------------------------------------------------------------------
# Cloud Scheduler - hourly batch prediction
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "batch_predict" {
  project          = var.project_id
  region           = var.region
  name             = "vayusetu-batch-predict"
  description      = "Aggregates recent citizen and satellite observations and requests 12-hour AQI forecasts."
  schedule         = var.batch_predict_schedule
  time_zone        = "Asia/Kolkata"
  attempt_deadline = "540s"

  retry_config {
    retry_count          = 1
    min_backoff_duration = "30s"
    max_backoff_duration = "300s"
  }

  http_target {
    http_method = "POST"
    uri         = local.batch_predict_url
    body = base64encode(jsonencode({
      trigger        = "cloud-scheduler"
      lookback_hours = var.batch_lookback_hours
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = local.batch_predict_url
    }
  }

  depends_on = [google_project_service.apis]
}
