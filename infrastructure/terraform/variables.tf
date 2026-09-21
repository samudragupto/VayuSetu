# -----------------------------------------------------------------------------
# VayuSetu - Input variables
# -----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Project and location
# ---------------------------------------------------------------------------

variable "project_id" {
  description = "Google Cloud project ID that hosts VayuSetu."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "region" {
  description = <<-EOT
    Primary region for Cloud Run, Cloud Functions, Cloud Storage, Artifact Registry
    and Cloud Scheduler. The default (us-central1) keeps Cloud Storage inside the
    Always Free tier. For India data residency switch to asia-south1 (Mumbai);
    the compute free tier still applies but regional storage is billed at
    roughly USD 0.023 per GB-month, which is negligible with the configured
    lifecycle rules.
  EOT
  type        = string
  default     = "us-central1"
}

variable "firestore_location" {
  description = "Location ID for the Firestore Native mode database. Must be compatible with the Eventarc trigger location used by the Cloud Functions (normally identical to var.region)."
  type        = string
  default     = "us-central1"
}

variable "bigquery_location" {
  description = "Location for the BigQuery dataset. Multi-region US is eligible for the free tier; use asia-south1 for India residency."
  type        = string
  default     = "US"
}

variable "environment" {
  description = "Deployment environment label (dev, staging, prod)."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of dev, staging or prod."
  }
}

# ---------------------------------------------------------------------------
# GitHub Actions - Workload Identity Federation
# ---------------------------------------------------------------------------

variable "github_repository" {
  description = "GitHub repository (owner/name) that is permitted to deploy through Workload Identity Federation."
  type        = string
  default     = "samudragupto/VayuSetu"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in the form owner/name."
  }
}

# ---------------------------------------------------------------------------
# Application configuration
# ---------------------------------------------------------------------------

variable "admin_domain" {
  description = "Email domain whose Google accounts may sign in to the authority dashboard (for example nagarnigam.gov.in)."
  type        = string
}

variable "gemini_model_candidates" {
  description = <<-EOT
    Comma separated, ordered list of Gemini model identifiers used by the vision
    function. The first entry honours the project specification (gemini-1.5-flash).
    Google retired the 1.5 family from the Gemini API, so the vision client
    transparently falls through to the next free-tier Flash model when it
    receives HTTP 404 or sustained HTTP 429 responses.
  EOT
  type        = string
  default     = "gemini-1.5-flash,gemini-flash-latest,gemini-3.5-flash-lite,gemini-2.5-flash"
}

variable "alert_aqi_threshold" {
  description = "Predicted 12-hour AQI value at or above which authority alerts are dispatched."
  type        = number
  default     = 300
}

variable "hotspot_geohash_precision" {
  description = "Geohash precision used to aggregate citizen reports into prediction cells (5 is roughly 4.9 km x 4.9 km)."
  type        = number
  default     = 5
}

variable "batch_predict_schedule" {
  description = "Cron schedule (Asia/Kolkata) for the batch prediction job. Hourly keeps the run well inside the free tiers."
  type        = string
  default     = "0 * * * *"
}

variable "batch_lookback_hours" {
  description = "Rolling window of citizen observations aggregated by each batch prediction run."
  type        = number
  default     = 6
}

variable "image_nearline_after_days" {
  description = "Age in days after which citizen images move to the Nearline storage class."
  type        = number
  default     = 30
}

variable "image_retention_days" {
  description = "Age in days after which citizen images are permanently deleted."
  type        = number
  default     = 90
}

variable "api_gateway_max_instances" {
  description = "Upper bound on Cloud Run instances for the WhatsApp API gateway. Caps spend in the unlikely event of a traffic spike."
  type        = number
  default     = 3
}

variable "prediction_max_instances" {
  description = "Upper bound on Cloud Run instances for the XGBoost prediction service."
  type        = number
  default     = 2
}

variable "placeholder_image" {
  description = "Public container image used when Cloud Run services are first created. GitHub Actions replaces it with the real image on the first deployment."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "enable_deletion_protection" {
  description = "When true, Firestore and BigQuery resources refuse to be destroyed by Terraform."
  type        = bool
  default     = false
}

variable "gee_project" {
  description = "Cloud project registered with Google Earth Engine (noncommercial tier). Defaults to project_id when empty."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Secrets - stored in Secret Manager and injected into Cloud Run / Functions
# ---------------------------------------------------------------------------

variable "twilio_account_sid" {
  description = "Twilio account SID used for WhatsApp and voice."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.twilio_account_sid) > 0
    error_message = "twilio_account_sid must not be empty (use a temporary value and rotate it later if necessary)."
  }
}

variable "twilio_auth_token" {
  description = "Twilio auth token used to validate webhooks and call the REST API."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.twilio_auth_token) > 0
    error_message = "twilio_auth_token must not be empty."
  }
}

variable "twilio_whatsapp_from" {
  description = "Twilio WhatsApp sender in the form whatsapp:+14155238886 (sandbox) or an approved business number."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^whatsapp:\\+[0-9]{8,15}$", var.twilio_whatsapp_from))
    error_message = "twilio_whatsapp_from must look like whatsapp:+14155238886."
  }
}

variable "twilio_voice_from" {
  description = "Twilio voice-capable phone number in E.164 form used for authority voice alerts (for example +14155550100)."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^\\+[0-9]{8,15}$", var.twilio_voice_from))
    error_message = "twilio_voice_from must be an E.164 phone number."
  }
}

variable "google_ai_studio_api_key" {
  description = "Google AI Studio API key (free tier) used by the Gemini vision function."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.google_ai_studio_api_key) > 0
    error_message = "google_ai_studio_api_key must not be empty."
  }
}

variable "phone_hash_secret" {
  description = "HMAC secret used to pseudonymise citizen phone numbers. Generated automatically when left empty."
  type        = string
  sensitive   = true
  default     = ""
}
